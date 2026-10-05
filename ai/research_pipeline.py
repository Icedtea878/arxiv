"""Abstract triage -> full-text reader -> independent judge -> dual reports."""
import argparse
import hashlib
import json
import os
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from langchain_openai import ChatOpenAI
from research_config import load_config, ROOT
from fulltext import fetch_fulltext, chunks
from resilient import fatal_provider_error
from runtime import build_chat_openai_kwargs

Grade = Literal['A','B','C','D','E']
PROMPTS = {name:(ROOT/'ai/prompts'/f'{name}.txt').read_text(encoding='utf-8') for name in ['triage','reader','judge','chunk']}
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Evidence(Strict):
    source_id:str=Field(min_length=1)
    quote:str=Field(default='',max_length=250)
    quote_kind:Literal['exact','context_excerpt']='exact'
class Triage(Strict):
    grade:Grade
    directions:list[str]
    research_object:str=Field(min_length=1)
    transfer:str=Field(min_length=1)
    reason:str=Field(min_length=1)
    uncertain:bool
    evidence:list[Evidence]
class Analysis(Triage):
    brief:list[str]=Field(min_length=2,max_length=6)
    sections:dict[str,str]
class Issue(Strict):
    source_id:str
    message:str=Field(min_length=1)
class Judgment(Strict):
    verdict:Literal['pass','revise','insufficient']
    grade:Grade
    directions:list[str]
    reason:str=Field(min_length=1)
    issues:list[Issue]
class Notes(Strict):
    notes:str=Field(min_length=1)
    evidence:list[Evidence]

def norm(value):
    value=unicodedata.normalize('NFKC',value).replace('\u00ad','').replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    value=value.translate(str.maketrans({c:'-' for c in '‐‑‒–—−'}))
    return ' '.join(value.split()).casefold()
def digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
def parse_json(response,schema):
    content=getattr(response,'content',response)
    if isinstance(content,list): content='\n'.join(b.get('text','') for b in content if isinstance(b,dict))
    if not isinstance(content,str): raise ValueError('Empty model response')
    for i,c in enumerate(content):
        if c!='{': continue
        try:
            value,_=json.JSONDecoder().raw_decode(content[i:])
        except ValueError: continue
        try:
            return schema.model_validate(value).model_dump()
        except ValueError as error:
            raise ValueError('Structured fields invalid: '+str(error)[:1800]) from error
    raise ValueError('Invalid JSON response')

def validate_result(value, config, sources):
    if not set(value.get('directions',[])) <= set(config['directions']): raise ValueError('Unknown research direction')
    if value.get('grade') in config['retain_grades'] and not value.get('directions'):
        raise ValueError('Retained grade requires a research direction')
    evidence=value.get('evidence',[])
    evidence_errors=[]
    for item in evidence:
        if not item.get('quote'):
            source=sources.get(item['source_id'])
            if not source:
                evidence_errors.append(f"Unknown evidence source {item['source_id']}");continue
            item['quote']=source['text'][:200]
            item['quote_kind']='context_excerpt'
        # A model may punctuate an excerpt that ends mid-sentence. Strip only
        # terminal punctuation; all words and internal punctuation stay exact.
        quote=item['quote'].rstrip(' .,:;!?。；，！？”')
        if len(quote)<8: raise ValueError('Evidence excerpt is too short')
        item['quote']=quote
        source=sources.get(item['source_id'])
        if not source or norm(item['quote']) not in norm(source['text']):
            # Resolve an exact quote misattributed to another supplied source.
            actual=next((sid for sid,body in sources.items() if norm(item['quote']) in norm(body['text'])),None)
            if actual:
                item['source_id']=actual
            else:
                evidence_errors.append(f"Evidence {item['source_id']}: quote not found verbatim: {item['quote'][:160]}")
    if evidence_errors:
        raise ValueError('\n'.join(evidence_errors)+'\nCopy short continuous spans; do not omit internal words or citations.')
    if value.get('grade') in config['retain_grades'] and 'evidence' in value and not evidence:
        raise ValueError('Retained grade requires evidence')
    if 'sections' in value:
        if set(value['sections']) != set(config['output']['sections']) or any(not v.strip() for v in value['sections'].values()):
            raise ValueError('Missing configured summary sections')
        if len(value['brief'])!=config['output']['brief_sentences']: raise ValueError('Incorrect brief sentence count')
    for issue in value.get('issues',[]):
        if issue['source_id']!='missing' and issue['source_id'] not in sources: raise ValueError('Unknown judge source ID')
    return value

class Engine:
    def __init__(self,config,cache_dir):
        self.config=config;self.cache_dir=Path(cache_dir);self.models={};self.usage=Counter();self.hits=0;self.calls=0
        self.context={k:config[k] for k in ['research_goal','directions','questions','grades','exclusions','examples','output']}
    def model(self,role):
        if role not in self.models:
            c=self.config['models']
            key=os.getenv('JUDGE_API_KEY') or os.getenv('OPENAI_API_KEY','') if role=='judge' else os.getenv('OPENAI_API_KEY','')
            base=(os.getenv('JUDGE_BASE_URL') or c['judge_base_url'] or os.getenv('OPENAI_BASE_URL') or c['base_url']) if role=='judge' else (os.getenv('OPENAI_BASE_URL') or c['base_url'])
            self.models[role]=ChatOpenAI(timeout=180,max_retries=1,**build_chat_openai_kwargs(c[role],base,key))
        return self.models[role]
    def call(self,stage,schema,payload,sources):
        role='reader' if stage in ['chunk','reader'] else stage
        key=digest(['research-v2-source-references',stage,PROMPTS[stage],self.config,payload,schema.model_json_schema(),os.getenv('OPENAI_BASE_URL'),os.getenv('JUDGE_BASE_URL')])
        path=self.cache_dir/'calls'/f'{key}.json'
        if path.exists():
            try:
                cached=schema.model_validate_json(path.read_text(encoding='utf-8')).model_dump()
                validate_result(cached,self.config,sources);self.hits+=1;return cached
            except (ValueError,TypeError): pass
        shape=schema.model_json_schema()
        if 'Evidence' in shape.get('$defs',{}):
            evidence_shape=shape['$defs']['Evidence']
            evidence_shape['properties']={'source_id':{'type':'string','enum':list(sources)}}
            evidence_shape['required']=['source_id']
        messages=[('system',PROMPTS[stage]+'\n只输出符合以下Schema的JSON：'+json.dumps(shape,ensure_ascii=False)),
                  ('human',json.dumps({'research_profile':self.context,**payload},ensure_ascii=False))]
        for attempt in range(3):
            parsed=None;response=None
            try:
                response=self.model(role).invoke(messages);self.calls+=1
                for k,v in (getattr(response,'usage_metadata',None) or {}).items():
                    if k in ['input_tokens','output_tokens','total_tokens'] and isinstance(v,int):self.usage[k]+=v
                parsed=parse_json(response,schema)
                value=validate_result(parsed,self.config,sources)
                write_json(path,value);return value
            except Exception as error:
                if isinstance(error,ValueError):
                    write_json(self.cache_dir/'rejected'/f'{key}-{attempt}.json', {'stage':stage,'error':str(error),'result':parsed,'raw_response':getattr(response,'content',None) if parsed is None else None})
                    if parsed is not None:
                        messages.append(('assistant',json.dumps(parsed,ensure_ascii=False)))
                    messages.append(('human','校验失败：'+str(error)[:2200]+'。请修正，不要改写原文引句；可以改用更短的连续原文片段，不能编造。重新输出完整JSON。'))
                if fatal_provider_error(error) or attempt==2: raise
                time.sleep(5*(attempt+1))

def judge_sources(document,analysis):
    sections=document['sections']
    if sum(len(s['text']) for s in sections)<=48000: return sections
    ids={e['source_id'] for e in analysis['evidence']}
    indices={j for i,s in enumerate(sections) if s['id'] in ids for j in [max(0,i-1),i,min(len(sections)-1,i+1)]}
    return [s for i,s in enumerate(sections) if i in indices]

def review_paper(engine,paper,triage,document):
    c=engine.config;sources={s['id']:s for s in document['sections']}
    parts=chunks(document['sections'],c['reading']['chunk_chars'])
    notes=[]
    if len(parts)>1:
        for part in parts:
            notes.append(engine.call('chunk',Notes,{'title':paper['title'],'text':part,'language':c['output']['language']}, {s['id']:s for s in part}))
    payload={'title':paper['title'],'abstract':paper['summary'],'coverage':document['notes'],
             'reading_material':notes if notes else document['sections']}
    if notes:
        # Programmatically copied source excerpts anchor chunk notes; the judge checks original paragraphs.
        payload['source_evidence']=[e for note in notes for e in note['evidence']]
    analysis=engine.call('reader',Analysis,payload,sources)
    history=[]
    for revision in range(c['reading']['max_revisions']+1):
        original=judge_sources(document,analysis)
        judge=engine.call('judge',Judgment,{'title':paper['title'],'abstract':paper['summary'],'analysis':analysis,
                      'original_sources':original,'coverage':document['notes'],
                      'review_scope':'all extracted text' if len(original)==len(document['sections']) else 'cited passages and adjacent context'},sources)
        history.append(judge)
        if judge['verdict']=='pass':break
        if judge['verdict']=='revise' and revision<c['reading']['max_revisions']:
            analysis=engine.call('reader',Analysis,{**payload,'previous_analysis':analysis,'judge_feedback':judge},sources)
        else:break
    pending=judge['verdict']!='pass' or analysis['uncertain'] or document['coverage']=='partial_text'
    return {'grade':judge['grade'],'directions':judge['directions'],'reason':judge['reason'],
            'status':'pending_review' if pending else 'reviewed','analysis':analysis,'judgments':history,
            'source':document['source'],'coverage':document['coverage'],'coverage_notes':document['notes'],
            'source_locations':{e['source_id']:sources[e['source_id']]['location'] for e in analysis['evidence']},
            'chunks_read':len(parts)}

def run(papers,config,cache_dir,fulltext_loader=fetch_fulltext,engine=None):
    engine=engine or Engine(config,cache_dir)
    records=[]; candidates=[];triage_failures=0
    for i,paper in enumerate(papers,1):
        source={'abstract':{'text':paper['summary'],'location':'摘要'}}
        row={**paper,'research_review':{}}
        try:
            triage=engine.call('triage',Triage,{'title':paper['title'],'abstract':paper['summary']},source)
            row['triage']=triage
            row['research_review']={'grade':triage['grade'],'directions':triage['directions'],'reason':triage['reason'],'status':'abstract_excluded'}
            borderline = triage['grade']=='D' and bool(triage['directions']) and bool(triage['evidence'])
            if borderline:
                row['triage_review_reason']='D级存在方向和原文线索，需全文裁判确认；不是最终排除。'
            if triage['grade'] in config['retain_grades'] or triage['uncertain'] or borderline:candidates.append(row)
        except Exception as error:
            if fatal_provider_error(error):raise
            triage_failures+=1
            row['research_review']={'grade':None,'directions':[],'reason':'摘要初筛失败，待重试','status':'triage_failed','error_type':type(error).__name__}
            candidates.append(row)
        records.append(row)
        print(f"初筛 [{i}/{len(papers)}] {paper['id']} {row['research_review']['grade']} {row['research_review']['status']}",flush=True)
    if papers and triage_failures==len(papers):raise RuntimeError('All triage requests failed; no report published')
    candidates.sort(key=lambda p:('ABCDE'.find(p['research_review']['grade']) if p['research_review']['grade'] else 5,p.get('research_rank',99999)))
    read_count=0
    for row in candidates:
        if row['research_review']['status']=='triage_failed':continue
        cap=config['reading']['max_fulltext_papers']
        if cap is not None and read_count>=cap:
            row['research_review']['status']='deferred';row['research_review']['reason']+='；达到配置的全文上限，等待阅读';continue
        read_count+=1
        try:
            document=fulltext_loader(row,Path(cache_dir)/'fulltext')
        except Exception as error:
            row['research_review'].update(status='fulltext_unavailable',error_type=type(error).__name__)
            print('全文获取失败',row['id'],type(error).__name__,str(error)[:180] if isinstance(error,(ValueError,RuntimeError)) else '',flush=True);continue
        try:
            row['research_review']=review_paper(engine,row,row['triage'],document)
        except Exception as error:
            if fatal_provider_error(error):raise
            row['research_review'].update(status='analysis_failed',error_type=type(error).__name__,source=document['source'],coverage_notes=document['notes'])
            if isinstance(error,ValueError):
                print('分析格式校验失败',row['id'],str(error)[:180],flush=True)
        print('全文复核',row['id'],row['research_review']['grade'],row['research_review']['status'],flush=True)
    retained=[p for p in records if p['research_review']['status'] not in ['abstract_excluded'] and
              (p['research_review']['status']!='reviewed' or p['research_review']['grade'] in config['retain_grades'])]
    retained.sort(key=lambda p:('ABCDE'.find(p['research_review']['grade']) if p['research_review']['grade'] else 5,p.get('research_rank',99999)))
    report={'config_hash':digest(config),'profile':config['name'],'generated_at':datetime.now(timezone.utc).isoformat(),
            'assessed':len(papers),'retained':len(retained),'reviewed':sum(p['research_review']['status']=='reviewed' for p in retained),
            'pending':sum(p['research_review']['status']!='reviewed' for p in retained),'grades':dict(Counter(p['research_review']['grade'] or '?' for p in retained)),
            'model_calls':engine.calls,'cache_hits':engine.hits,'usage':dict(engine.usage),'models':config['models'],
            'decisions':[{'id':p['id'],'title':p['title'],'triage':p.get('triage'),'review':p['research_review']} for p in records]}
    return retained,report

STATUS={'reviewed':'已通过裁判复核','pending_review':'待复核','fulltext_unavailable':'全文未获取，仅有摘要初筛','analysis_failed':'全文分析未完成','triage_failed':'初筛失败，待重试','deferred':'达到全文上限，等待阅读'}
def md(value): return str(value).replace('<','&lt;').replace('>','&gt;')
def reports_markdown(papers,report,config,date):
    intro=f"# {date} · {config['name']}\n\n评估 {report['assessed']} 篇；收录 {report['retained']} 篇（已复核 {report['reviewed']}，待处理 {report['pending']}）。生成时间：{report['generated_at']}。\n\n按 A→B→C 排序，同级按关键词预选顺序；等级表示研究相关性，不代表论文质量。待复核条目的等级为暂定。\n"
    brief=[intro,'## 精简版\n'];detail=[intro,'## 详细版\n']
    for i,p in enumerate(papers,1):
        r=p['research_review'];url='https://arxiv.org/abs/'+p['id']
        head=f"\n## {i}. {md(p['title'])}\n\n等级 **{r['grade'] or '待定'}** · {STATUS[r['status']]} · [论文]({url})\n\n"
        brief.append(head);detail.append(head)
        analysis=r.get('analysis')
        if not analysis:
            line=f"**本篇未完成全文阅读总结。** {md(r['reason'])}\n\n原始摘要：{md(p.get('summary',''))}\n"
            brief.append('本篇未完成全文阅读总结：'+md(r['reason'])+'\n');detail.append(line);continue
        brief.extend('- '+md(sentence)+'\n' for sentence in analysis['brief'])
        detail.append('**相关性依据：** '+md(r['reason'])+'\n\n')
        detail.append('**研究对象：** '+md(analysis['research_object'])+'\n\n**迁移建议（模型推断）：** '+md(analysis['transfer'])+'\n')
        for title in config['output']['sections']:detail.append(f"\n### {md(title)}\n\n{md(analysis['sections'][title])}\n")
        detail.append('\n### 证据定位与阅读范围\n\n')
        for sid,location in r['source_locations'].items():
            target=r['source']+(f'#page={sid[1:]}' if r['source'].startswith('https://arxiv.org/pdf/') and re.fullmatch('p[0-9]+',sid) else '')
            detail.append(f'- [{sid}] [{md(location)}]({target})\n')
        detail.append('\n'+'；'.join(map(md,r['coverage_notes']))+'\n')
        issues=[issue['message'] for j in r['judgments'][-1:] for issue in j['issues']]
        if issues:detail.append('\n裁判待核问题：'+'；'.join(map(md,issues))+'\n')
    return ''.join(brief),''.join(detail)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args();config=load_config(args.config)
    papers=[json.loads(x) for x in args.data.read_text(encoding='utf-8').splitlines() if x.strip()]
    retained,report=run(papers,config,ROOT/'.ai-cache/research')
    output=args.output_dir or args.data.parent;output.mkdir(parents=True,exist_ok=True)
    date=args.data.stem.split('_')[0]
    write_json(output/f'{date}_research_report.json',report)
    target=output/f'{date}_research.jsonl';temp=target.with_suffix('.tmp')
    temp.write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in retained),encoding='utf-8');temp.replace(target)
    brief,detail=reports_markdown(retained,report,config,date)
    (output/f'{date}_brief.md').write_text(brief,encoding='utf-8');(output/f'{date}_detailed.md').write_text(detail,encoding='utf-8')
    summary=f"## 全文阅读与裁判复核\n\n评估 {report['assessed']} 篇；报告收录 {len(retained)} 篇；已复核 {report['reviewed']} 篇；待处理 {report['pending']} 篇。\n\n|论文|等级|状态|\n|---|---|---|\n"
    summary+=''.join(f"|{p['title'].replace('|','/')}|{p['research_review']['grade'] or '?'}|{STATUS[p['research_review']['status']]}|\n" for p in retained)
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as out:out.write(summary)
if __name__=='__main__':main()
