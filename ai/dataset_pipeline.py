"""A persistent dataset backlog, bounded evidence review and daily shortlist."""
import argparse
import copy
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import requests
from langchain_openai import ChatOpenAI
from lxml import html
from pydantic import BaseModel, ConfigDict, Field
from research_config import ROOT, load_config
from research_pipeline import digest, parse_json, write_json
from resilient import fatal_provider_error
from runtime import build_chat_openai_kwargs

PROMPT=(ROOT/'ai/prompts/dataset.txt').read_text(encoding='utf-8')
ID_RE=re.compile(r'[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)?\Z')
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Fact(Strict):
    status:Literal['known','unknown']
    value:str=Field(min_length=1,max_length=600)
    evidence:list[str]
class Review(Strict):
    grade:Literal['A','B','C','D','E']
    directions:list[str]
    suitability:Literal['usable','conditional','unknown']
    overview:str=Field(min_length=8,max_length=600)
    application:str=Field(min_length=8,max_length=800)
    reason:str=Field(min_length=8,max_length=1000)
    origin:Fact
    individual_id:Fact
    time_info:Fact
    labels:Fact
    constraints:list[str]=Field(max_length=6)
    evidence:list[str]

def valid_id(identifier):
    return isinstance(identifier,str) and bool(ID_RE.fullmatch(identifier)) and '..' not in identifier
def days_since(day,today):
    try:return (date.fromisoformat(today)-date.fromisoformat(day[:10])).days
    except (ValueError,TypeError):return 9999
def terms(config):
    groups=list(config['datasets']['queries'].values())
    broad=[g[i] for i in range(max(map(len,groups),default=0)) for g in groups if i<len(g)]
    return list(dict.fromkeys(broad+config['keyword_profile'].get('dataset_names',[])))
def normalized(value):
    return re.sub(r'[^\w]+',' ',str(value).casefold()).strip()
def metadata_rank(row,config):
    text=normalized(' '.join([row['id'],row.get('description',''),*row.get('tags',[])]))
    words=set(terms(config))|set(config['keyword_profile']['method_keywords'])
    return sum((4 if normalized(t) in normalized(row['id']) else 1) for t in words if normalized(t) and normalized(t) in text)
def slim(row):
    keys=['id','description','tags','downloads','gated','lastModified','sha','cardData']
    out={k:row[k] for k in keys if k in row}
    out['description']=str(out.get('description',''))[:2000]
    out['tags']=[str(t)[:150] for t in (out.get('tags') or [])][:80]
    card=out.get('cardData') or {}
    if not isinstance(card,dict):card={}
    if len(json.dumps(card,ensure_ascii=False))>6000:
        card={k:card[k] for k in ['license','pretty_name','task_categories','language','annotations_creators','source_datasets'] if k in card}
    out['cardData']=card
    return out

class RateLimited(RuntimeError):pass
class Hub:
    """Fixed public endpoints, serial bounded reads; never fetch whole datasets."""
    def __init__(self):self.last=0;self.session=requests.Session()
    def get(self,url,params=None,limit=2_000_000):
        time.sleep(max(0,.75-(time.monotonic()-self.last)));self.last=time.monotonic()
        for attempt in range(2):
            try:
                with self.session.get(url,params=params,timeout=(10,35),stream=True,headers={'User-Agent':'SocialWorldModelDatasetDiscovery/1.0'}) as r:
                    if r.status_code==429:raise RateLimited('Source rate-limited; remaining source requests postponed')
                    r.raise_for_status();data=bytearray()
                    for block in r.iter_content(32768):
                        data.extend(block)
                        if len(data)>limit:raise ValueError('Source response exceeds bounded read limit')
                    return bytes(data)
            except RateLimited:raise
            except requests.RequestException:
                if attempt:raise
                time.sleep(2)
    def json(self,url,params=None):return json.loads(self.get(url,params))
    def search(self,term,sort,limit):
        rows=self.json('https://huggingface.co/api/datasets',{'search':term,'sort':sort,'direction':-1,'limit':limit,'full':'true'})
        if not isinstance(rows,list):raise ValueError('Invalid dataset listing')
        return rows
    def evidence(self,row,config):
        identifier=row['id'];encoded=quote(identifier,safe='/')
        if not valid_id(identifier):raise ValueError('Invalid dataset ID')
        info=self.json('https://huggingface.co/api/datasets/'+encoded)
        card_url='https://huggingface.co/datasets/'+encoded+'/resolve/main/README.md'
        sources={'metadata':{'url':'https://huggingface.co/datasets/'+encoded,'text':json.dumps(slim(info),ensure_ascii=False)}}
        warnings=[];card=''
        try:
            card=self.get(card_url,limit=500_000).decode('utf-8',errors='replace')
            sources['card']={'url':'https://huggingface.co/datasets/'+encoded+'/blob/main/README.md','text':card[:config['datasets']['card_chars']]}
            if len(card)>config['datasets']['card_chars']:warnings.append('数据卡超过阅读上限，仅检查开头；信息可能不完整。')
        except RateLimited:raise
        except (requests.RequestException,ValueError):warnings.append('README未获取；使用公开元数据与可用字段。')
        features=[]
        try:
            splits=self.json('https://datasets-server.huggingface.co/splits',{'dataset':identifier}).get('splits',[])
            if splits:
                split=splits[0]
                params={'dataset':identifier,'config':split['config'],'split':split['split'],'offset':0,'length':3}
                preview=self.json('https://datasets-server.huggingface.co/rows',params)
                features=preview.get('features',[])
                sources['fields']={'url':'https://huggingface.co/datasets/'+encoded,'text':json.dumps({'config':split['config'],'split':split['split'],'features':features},ensure_ascii=False)[:8000]}
                # Only three bounded public examples reach the reviewer, not published state.
                sources['sample']={'url':sources['fields']['url'],'text':json.dumps(preview.get('rows',[])[:3],ensure_ascii=False)[:5000]}
        except RateLimited:raise
        except (requests.RequestException,ValueError,KeyError):warnings.append('字段预览未获取（可能需申请或不支持预览）；未确认的属性标为未知。')
        paper_ids=list(dict.fromkeys(re.findall(r'arxiv:(\d{4}\.\d{4,5}(?:v\d+)?)',' '.join(info.get('tags',[])))+re.findall(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)',card)))[:3]
        # One linked paper abstract, if available; no full-paper reading in this workflow.
        if paper_ids:
            try:
                time.sleep(3)
                tree=html.fromstring(self.get('https://arxiv.org/abs/'+paper_ids[0]))
                abstract=tree.xpath('//blockquote[contains(@class,"abstract")]')
                if abstract:sources['paper']={'url':'https://arxiv.org/abs/'+paper_ids[0],'text':' '.join(abstract[0].text_content().split())[:6000]}
            except RateLimited:warnings.append('关联论文来源限流，本次未读取摘要。')
            except (requests.RequestException,ValueError):warnings.append('关联论文摘要未获取。')
        # Exclude download counts, repo timestamps and sample rows from meaningful-update detection.
        attrs={k:info.get(k) for k in ['description','tags','gated','cardData']}
        fingerprint=digest([card,features,attrs])
        mirror=digest([card,features]) if len(card)>500 and features else None
        return {'sources':sources,'fingerprint':fingerprint,'mirror':mirror,'info':slim(info),'warnings':warnings,'papers':paper_ids}

def validate_review(value,config,sources):
    if not set(value['directions'])<=set(config['directions']):raise ValueError('Unknown research direction')
    ids=set(value['evidence'])
    for name in ['origin','individual_id','time_info','labels']:
        fact=value[name];ids.update(fact['evidence'])
        if fact['status']=='known' and not fact['evidence']:raise ValueError(name+' requires a source; otherwise mark unknown')
        if fact['status']=='unknown':fact['value']='unknown';fact['evidence']=[]
    if not ids<=set(sources):raise ValueError('Only provided source IDs may be cited')
    if value['origin']['value'] not in ['real','synthetic','mixed','unknown']:raise ValueError('Invalid origin value')
    if value['grade'] in 'ABC' and (not value['directions'] or not value['evidence']):raise ValueError('Relevant datasets require a direction and source evidence')
    return value

class Reviewer:
    def __init__(self,config,cache):self.config=config;self.cache=Path(cache);self.calls=0;self.hits=0;self.usage=Counter();self.model=None
    def review(self,row,document):
        c=self.config
        profile={k:c[k] for k in ['research_goal','directions','questions','exclusions']}
        base=os.getenv('OPENAI_BASE_URL') or c['models']['base_url']
        key=digest([PROMPT,profile,c['datasets']['model'],base,document['fingerprint']])
        path=self.cache/(key+'.json');sources=document['sources']
        if path.exists():
            try:
                result=Review.model_validate_json(path.read_text()).model_dump();validate_review(result,c,sources);self.hits+=1;return result
            except (ValueError,KeyError):pass
        if self.model is None:self.model=ChatOpenAI(timeout=150,max_retries=1,**build_chat_openai_kwargs(c['datasets']['model'],base,os.getenv('OPENAI_API_KEY','')))
        unknown={'status':'unknown','value':'unknown','evidence':[]}
        example={'grade':'C','directions':[next(iter(c['directions']))],'suitability':'unknown','overview':'填写数据内容','application':'填写具体可尝试任务及条件','reason':'填写判断依据',
                 **{name:unknown for name in ['origin','individual_id','time_info','labels']},'constraints':['填写实际限制'],'evidence':['card']}
        messages=[('system',PROMPT+'\n字段校验规则（不输出规则本身）：'+json.dumps(Review.model_json_schema(),ensure_ascii=False)+'\n填好的数据实例示例（所有值需依据实际材料替换）：'+json.dumps(example,ensure_ascii=False)),
                  ('human',json.dumps({'profile':profile,'language':c['output']['language'],'dataset':row['id'],'sources':sources,'coverage':document['warnings']},ensure_ascii=False))]
        for attempt in range(2):
            try:
                response=self.model.invoke(messages);self.calls+=1
                for k,v in (getattr(response,'usage_metadata',None) or {}).items():
                    if k in ['input_tokens','output_tokens','total_tokens'] and isinstance(v,int):self.usage[k]+=v
                value=validate_review(parse_json(response,Review),c,sources);write_json(path,value);return value
            except Exception as error:
                if fatal_provider_error(error) or attempt:raise
                messages.append(('human','校验错误：'+str(error)[:1200]+'。只返回修正后填好的JSON数据实例，不返回Schema。'))

def pick(candidates,state,config,feedback):
    profile=digest([config['research_goal'],config['directions'],config['datasets']['model'],PROMPT])
    ready=[];aliases=config['datasets']['aliases']
    preference=Counter()
    for identifier,label in feedback.items():
        if label=='useful':preference.update(state['candidates'].get(identifier,{}).get('review',{}).get('directions',[]))
    for row in candidates:
        review=row.get('review');identifier=row['id']
        if not review or row.get('review_profile')!=profile or review['grade'] not in 'ABC':continue
        if feedback.get(identifier) in ['seen','not_relevant'] or feedback.get(aliases.get(identifier,'')) in ['seen','not_relevant']:continue
        canonical=aliases.get(identifier) or ('mirror:'+row['mirror'] if row.get('mirror') else identifier)
        rec_key=digest([canonical,row.get('mirror') or row['fingerprint'],profile])
        if rec_key in state['recommended']:continue
        ready.append({**row,'canonical':canonical,'recommendation_key':rec_key})
    selected=[];counts=Counter();families=set()
    while ready and len(selected)<config['datasets']['daily_limit']:
        ready.sort(key=lambda r:('ABCDE'.index(r['review']['grade']),min((counts[d] for d in r['review']['directions']),default=0),
                                ['usable','conditional','unknown'].index(r['review']['suitability']),-sum(preference[d] for d in r['review']['directions']),-r.get('rank',0),r['id']))
        row=ready.pop(0)
        if row['canonical'] in families:continue
        families.add(row['canonical']);selected.append(row);counts.update(row['review']['directions'])
    return selected

def run(config,state,today,hub,reviewer,feedback=None):
    state=copy.deepcopy(state or {'version':1,'candidates':{},'recommended':{},'query_cursor':0})
    settings=config['datasets'];warnings=[];all_terms=terms(config);cursor=state['query_cursor'];success=0
    plan=[all_terms[(cursor+i)%len(all_terms)] for i in range(min(settings['queries_per_day'],len(all_terms)))]
    for term in plan:
        for sort in ['lastModified','downloads']:
            try:
                for item in hub.search(term,sort,(settings['results_per_query']+1)//2):
                    if not valid_id(item.get('id')) or item.get('private') or item.get('disabled'):continue
                    identifier=item['id'];old=state['candidates'].get(identifier,{})
                    row={**old,**slim(item),'first_seen':old.get('first_seen',today),'last_seen':today,
                         'retrieval_terms':list(dict.fromkeys(old.get('retrieval_terms',[])+[term]))}
                    row['rank']=metadata_rank(row,config);state['candidates'][identifier]=row
                success+=1
            except RateLimited:warnings.append('检索来源限流；本次候选可能不完整。');break
            except (requests.RequestException,ValueError):warnings.append('部分检索未完成：'+term)
        if warnings and '限流' in warnings[-1]:break
    if not success and not state['candidates']:raise RuntimeError('No dataset source could be queried; existing daily results preserved')
    state['query_cursor']=(cursor+len(plan))%len(all_terms)
    profile=digest([config['research_goal'],config['directions'],settings['model'],PROMPT])
    feedback=feedback or {};todo=[]
    for row in state['candidates'].values():
        if feedback.get(row['id']) in ['seen','not_relevant']:continue
        needs=row.get('review_profile')!=profile or row.get('review_sha')!=row.get('sha') or days_since(row.get('checked_at',''),today)>=settings['recheck_days']
        if needs:todo.append(row)
    todo.sort(key=lambda r:(-r.get('rank',0),r.get('checked_at',''),r['id']))
    reviewed=failures=0
    for row in todo[:settings['review_limit']]:
        try:
            document=hub.evidence(row,config)
            if row.get('fingerprint')==document['fingerprint'] and row.get('review_profile')==profile and row.get('review'):
                row.update(checked_at=today,review_sha=row.get('sha'));continue
            review=reviewer.review(row,document)
            row.update(review=review,review_profile=profile,checked_at=today,review_sha=row.get('sha'),fingerprint=document['fingerprint'],mirror=document['mirror'],
                       source_links={k:v['url'] for k,v in document['sources'].items()},coverage_notes=document['warnings'],papers=document['papers'],info=document['info'])
            reviewed+=1;print('数据集评审',row['id'],review['grade'],flush=True)
        except RateLimited:warnings.append('数据卡来源限流；剩余候选留到后续运行。');break
        except Exception as error:
            if fatal_provider_error(error):raise
            failures+=1;print('数据集评审待重试',row['id'],type(error).__name__,str(error)[:150] if isinstance(error,ValueError) else '',flush=True)
    if todo and failures==min(len(todo),settings['review_limit']):raise RuntimeError('All dataset evidence reviews failed; no new results published')
    selected=pick(list(state['candidates'].values()),state,config,feedback)
    rows=[]
    for row in selected:
        previous=any(v['canonical']==row['canonical'] for v in state['recommended'].values())
        item={k:row[k] for k in ['id','review','source_links','coverage_notes','papers','fingerprint']}
        item.update(url='https://huggingface.co/datasets/'+row['id'],reason_type='实质更新或研究档案变更' if previous else '首次推荐（可为历史数据集）',last_modified=row.get('lastModified'),license=(row.get('info',{}).get('cardData') or {}).get('license') or '未知',gated=row.get('info',{}).get('gated',False))
        rows.append(item);state['recommended'][row['recommendation_key']]={'id':row['id'],'canonical':row['canonical'],'date':today}
    # Bound the backlog while recommendation history continues to prevent repeats.
    ranked=sorted(state['candidates'].values(),key=lambda r:(r.get('last_seen',''),r.get('rank',0)),reverse=True)[:settings['candidate_limit']]
    state['candidates']={r['id']:r for r in ranked}
    report={'version':1,'date':today,'generated_at':datetime.now(timezone.utc).isoformat(),'profile':config['name'],'directions':config['directions'],
            'datasets':rows,'candidate_count':len(state['candidates']),'reviewed_this_run':reviewed,'review_failures':failures,'warnings':list(dict.fromkeys(warnings)),
            'limits':{'review':settings['review_limit'],'recommend':settings['daily_limit']},'model_calls':reviewer.calls,'cache_hits':reviewer.hits,'usage':dict(reviewer.usage)}
    return state,report

def markdown(report):
    text=[f"# {report['date']} · 每日数据集精选\n\n推荐 {len(report['datasets'])} 个；本次评审 {report['reviewed_this_run']} 个。用途是研究迁移建议，未查清的属性标为未知。\n"]
    for row in report['datasets']:
        r=row['review'];text.append(f"\n## [{row['id']}]({row['url']}) · {r['grade']}\n\n{r['overview']}\n\n用途（推断）：{r['application']}\n\n依据：{r['reason']}\n\n")
        for key,label in [('origin','来源'),('individual_id','个体ID'),('time_info','时间'),('labels','标签')]:text.append(f"- {label}：{r[key]['value']}\n")
        text.append('- 许可：'+str(row['license'])+'\n')
        text.extend('- 限制：'+v+'\n' for v in r['constraints']+row['coverage_notes'])
        text.extend(f"- [证据 {sid}]({row['source_links'][sid]})\n" for sid in r['evidence'])
    if report['warnings']:text.append('\n检索提示：'+'；'.join(report['warnings'])+'\n')
    return ''.join(text)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--date',default=datetime.now(timezone.utc).date().isoformat());parser.add_argument('--output',type=Path,default=ROOT/'data/datasets');parser.add_argument('--review-limit',type=int)
    args=parser.parse_args();config=load_config()
    if not config['datasets']['enabled']:print('Dataset selection disabled');return
    if args.review_limit:config['datasets']['review_limit']=min(args.review_limit,config['datasets']['review_limit'])
    output=args.output;output.mkdir(parents=True,exist_ok=True);target=output/(args.date+'.json')
    if target.exists():print('Daily dataset selection already published; keeping the same recommendations');return
    state=json.loads((output/'state.json').read_text()) if (output/'state.json').exists() else None
    feedback=json.loads((ROOT/'dataset_feedback.json').read_text()).get('feedback',{}) if (ROOT/'dataset_feedback.json').exists() else {}
    state,report=run(config,state,args.date,Hub(),Reviewer(config,ROOT/'.ai-cache/datasets/reviews'),feedback)
    write_json(target,report);write_json(output/'state.json',state)
    index=json.loads((output/'index.json').read_text()) if (output/'index.json').exists() else {'dates':[]}
    index['dates']=sorted(set(index['dates']+[args.date]),reverse=True);write_json(output/'index.json',index)
    (output/(args.date+'.md')).write_text(markdown(report),encoding='utf-8')
    summary=f"数据集精选：{len(report['datasets'])} 个；本次评审 {report['reviewed_this_run']} 个；上限 {config['datasets']['review_limit']}/{config['datasets']['daily_limit']}。"
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write('## '+summary+'\n')
if __name__=='__main__':main()
