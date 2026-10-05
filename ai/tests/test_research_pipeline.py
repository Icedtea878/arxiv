import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from research_config import load_config
from research_pipeline import run, reports_markdown, validate_result, review_paper
from fulltext import chunks, html_sections

TEXT='We simulate human cooperation and evaluate decisions using repeated interactions.'
EVIDENCE=[{'source_id':'s1','quote':'We simulate human cooperation'}]
def analysis():
    return {'grade':'A','directions':['interaction'],'research_object':'合作决策','transfer':'可尝试用于社会交互模拟','reason':'直接研究合作','uncertain':False,
            'evidence':EVIDENCE,'brief':['洞见。','方法。','用途。','限制。'],
            'sections':{k:'研究合作行为 [s1]。' for k in load_config()['output']['sections']}}
def document():
    return {'sections':[{'id':'s1','location':'Results','text':TEXT}],'notes':['文字已提取，图表未核验'],'source':'https://arxiv.org/html/1234.12345v1','coverage':'extracted_text'}
class FakeEngine:
    def __init__(self,judge_grades=None,verdicts=None):
        self.config=load_config();self.calls=0;self.hits=0;self.usage=Counter();self.stages=[]
        self.judge_grades=iter(judge_grades or ['A']);self.verdicts=iter(verdicts or ['pass'])
    def call(self,stage,schema,payload,sources):
        self.calls+=1;self.stages.append(stage)
        if stage=='triage':
            return {k:v for k,v in analysis().items() if k not in ['brief','sections']}
        if stage=='reader':return analysis()
        if stage=='judge':return {'verdict':next(self.verdicts),'grade':next(self.judge_grades),'directions':['interaction'],'reason':'证据支持','issues':[]}
        raise AssertionError(stage)

class ResearchPipelineTests(unittest.TestCase):
    def setUp(self):
        self.config=load_config();self.paper={'id':'1234.12345v1','title':'Cooperation','summary':TEXT,'categories':['cs.AI']}
    def test_fabricated_evidence_rejected(self):
        draft=analysis();draft['evidence']=[{'source_id':'s1','quote':'We achieved 99% accuracy'}]
        with self.assertRaises(ValueError):validate_result(draft,self.config,{'s1':{'text':TEXT}})
    def test_excerpt_terminal_punctuation_is_normalized(self):
        draft=analysis();draft['evidence']=[{'source_id':'s1','quote':'We simulate human cooperation.'}]
        result=validate_result(draft,self.config,{'s1':{'text':TEXT}})
        self.assertEqual(result['evidence'][0]['quote'],'We simulate human cooperation')
    def test_typographic_hyphen_and_minus_are_equivalent(self):
        draft=analysis();draft['evidence']=[{'source_id':'s1','quote':'cue-trigger pairs achieve p=1.7×10-7'}]
        validate_result(draft,self.config,{'s1':{'text':'The cue–trigger pairs achieve p=1.7×10−7 in this test.'}})
    def test_excerpt_internal_words_and_numbers_stay_exact(self):
        for quote in ['We simulate animal cooperation.', 'We evaluate 99% accuracy.']:
            draft=analysis();draft['evidence']=[{'source_id':'s1','quote':quote}]
            with self.assertRaises(ValueError):validate_result(draft,self.config,{'s1':{'text':TEXT}})
    def test_final_judge_grade_can_exclude(self):
        engine=FakeEngine(['D'])
        with tempfile.TemporaryDirectory() as d:
            kept,report=run([self.paper],self.config,d,lambda *_:document(),engine)
        self.assertEqual(kept,[]);self.assertEqual(report['decisions'][0]['review']['grade'],'D')
    def test_borderline_evidence_reaches_fulltext_judge(self):
        engine=FakeEngine(['C'])
        original=engine.call
        def call(stage,*args):
            value=original(stage,*args)
            if stage=='triage': value['grade']='D'
            return value
        engine.call=call
        with tempfile.TemporaryDirectory() as d:
            kept,report=run([self.paper],self.config,d,lambda *_:document(),engine)
        self.assertEqual(kept[0]['triage']['grade'],'D')
        self.assertEqual(kept[0]['research_review']['grade'],'C')
        self.assertIn('judge',engine.stages)
    def test_only_one_revision_and_pending_retained(self):
        engine=FakeEngine(['C','C'],['revise','revise'])
        with tempfile.TemporaryDirectory() as d:
            kept,report=run([self.paper],self.config,d,lambda *_:document(),engine)
        self.assertEqual(engine.stages.count('reader'),2)
        self.assertEqual(engine.stages.count('judge'),2)
        self.assertEqual(report['pending'],1)
        self.assertEqual(kept[0]['research_review']['status'],'pending_review')
    def test_fulltext_failure_keeps_placeholder_in_both_reports(self):
        def fail(*_):raise ValueError('no full text')
        with tempfile.TemporaryDirectory() as d:
            kept,report=run([self.paper],self.config,d,fail,FakeEngine())
        brief,detail=reports_markdown(kept,report,self.config,'2026-10-05')
        self.assertIn('Cooperation',brief);self.assertIn('Cooperation',detail)
        self.assertIn('未完成全文阅读',brief);self.assertEqual(report['pending'],1)
    def test_reports_share_papers_and_sections(self):
        with tempfile.TemporaryDirectory() as d:
            kept,report=run([self.paper],self.config,d,lambda *_:document(),FakeEngine())
        brief,detail=reports_markdown(kept,report,self.config,'2026-10-05')
        self.assertEqual(brief.count('## 1. Cooperation'),1);self.assertEqual(detail.count('## 1. Cooperation'),1)
        self.assertIn('核心 insight',detail);self.assertIn('Results',detail)
    def test_chunks_cover_all_text(self):
        sections=[{'id':'p1','text':'a'*21},{'id':'p2','text':'b'*19}]
        result=chunks(sections,10)
        self.assertEqual(''.join(p['text'] for c in result for p in c),'a'*21+'b'*19)
        self.assertTrue(all(sum(len(p['text']) for p in c)<=10 for c in result))
    def test_html_requires_full_article(self):
        with self.assertRaises(ValueError):html_sections(b'<html><p>abstract only</p></html>')
    def test_html_math_does_not_duplicate_tex_annotations(self):
        body='<article class="ltx_document"><p>'+('Full text. '*220)+'p=<math><semantics><mn>0.012</mn><annotation encoding="application/x-tex">0.012</annotation></semantics></math>, confirmed.</p></article>'
        sections,_=html_sections(body.encode())
        self.assertIn('p=0.012, confirmed.',sections[0]['text'])
        self.assertNotIn('0.0120.012',sections[0]['text'])
    def test_config_accepts_custom_directions(self):
        from research_config import ResearchConfig
        c=copy.deepcopy(self.config);c['directions']={'biology':'细胞行为'}
        self.assertEqual(ResearchConfig.model_validate(c).directions,{'biology':'细胞行为'})

class ModelCacheTests(unittest.TestCase):
    def test_validated_stage_result_is_reused(self):
        from research_pipeline import Engine,Triage
        from types import SimpleNamespace
        from unittest.mock import Mock
        config=load_config()
        payload={k:v for k,v in analysis().items() if k not in ['brief','sections']}
        payload['evidence']=[{'source_id':'abstract','quote':'We simulate human cooperation'}]
        model=Mock();model.invoke.return_value=SimpleNamespace(content=json.dumps(payload),usage_metadata={'input_tokens':20,'output_tokens':10})
        with tempfile.TemporaryDirectory() as d:
            e=Engine(config,d);e.models['triage']=model
            sources={'abstract':{'text':TEXT}}
            a=e.call('triage',Triage,{'title':'test','abstract':TEXT},sources)
            b=e.call('triage',Triage,{'title':'test','abstract':TEXT},sources)
            self.assertEqual(a,b);self.assertEqual(e.hits,1);model.invoke.assert_called_once()
