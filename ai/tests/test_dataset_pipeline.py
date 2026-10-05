import copy
import tempfile
import unittest
from collections import Counter
from dataset_pipeline import run,validate_review,digest,markdown,refresh_existing,RateLimited
from research_config import load_config

def review(grade='A',direction='individual'):
    unknown={'status':'unknown','value':'unknown','evidence':[]}
    return {'grade':grade,'directions':[direction],'suitability':'unknown','overview':'记录用户多轮对话中的行为线索。',
            'application':'可尝试用于个体历史对后续行为的预测，需验证标签。','reason':'数据卡明确包含用户历史与行为任务线索。',
            **{k:copy.deepcopy(unknown) for k in ['origin','individual_id','time_info','labels']},'constraints':['ID与时间字段尚未确认。'],'evidence':['card']}
class FakeHub:
    def __init__(self,n=8,mirror=None,version='v1'):
        self.rows=[{'id':f'test/persona{i}','description':'user simulation','sha':version,'cardData':{}} for i in range(n)];self.read=[];self.mirror=mirror;self.version=version
    def search(self,*args):return self.rows
    def evidence(self,row,config):
        self.read.append(row['id'])
        return {'sources':{'card':{'url':'https://huggingface.co/datasets/'+row['id'],'text':'Dataset card'}},'fingerprint':digest([row['id'],self.version]),
                'mirror':self.mirror,'info':row,'warnings':[],'papers':[]}
class FakeReviewer:
    def __init__(self,grade='A'):self.calls=0;self.hits=0;self.usage=Counter();self.grade=grade
    def review(self,*args):self.calls+=1;return review(self.grade)
class DatasetTests(unittest.TestCase):
    def setUp(self):self.config=load_config();self.config['datasets'].update(review_limit=6,daily_limit=3,queries_per_day=1)
    def test_review_and_recommendation_limits_and_unknown_fields(self):
        hub=FakeHub();state,report=run(self.config,None,'2026-10-05',hub,FakeReviewer())
        self.assertEqual(len(hub.read),6);self.assertEqual(len(report['datasets']),3)
        self.assertTrue(all(r['review']['individual_id']['status']=='unknown' for r in report['datasets']))
    def test_history_uses_unseen_backlog_and_does_not_repeat(self):
        state,first=run(self.config,None,'2026-10-05',FakeHub(),FakeReviewer())
        state,second=run(self.config,state,'2026-10-06',FakeHub(),FakeReviewer())
        self.assertFalse(set(r['id'] for r in first['datasets'])&set(r['id'] for r in second['datasets']))
    def test_meaningful_update_can_be_recommended_again(self):
        state,first=run(self.config,None,'2026-10-05',FakeHub(1),FakeReviewer())
        state,second=run(self.config,state,'2026-10-06',FakeHub(1,version='v2'),FakeReviewer())
        self.assertEqual(first['datasets'][0]['id'],second['datasets'][0]['id'])
        self.assertIn('更新',second['datasets'][0]['reason_type'])
    def test_identical_mirrors_never_fill_multiple_slots_or_repeat(self):
        state,first=run(self.config,None,'2026-10-05',FakeHub(mirror='same-original'),FakeReviewer())
        self.assertEqual(len(first['datasets']),1)
        state,second=run(self.config,state,'2026-10-06',FakeHub(mirror='same-original'),FakeReviewer())
        self.assertEqual(second['datasets'],[])
    def test_feedback_excludes_seen_and_irrelevant(self):
        state,r=run(self.config,None,'2026-10-05',FakeHub(),FakeReviewer(),{'test/persona0':'seen','test/persona1':'not_relevant'})
        self.assertFalse({'test/persona0','test/persona1'}&set(x['id'] for x in r['datasets']))
    def test_d_datasets_not_recommended_or_forced_to_fill(self):
        _,r=run(self.config,None,'2026-10-05',FakeHub(),FakeReviewer('D'))
        self.assertEqual(r['datasets'],[])
    def test_facts_cannot_claim_known_without_sources(self):
        r=review();r['individual_id']={'status':'known','value':'stable person ID','evidence':[]}
        with self.assertRaises(ValueError):validate_review(r,self.config,{'card':{}})
    def test_limited_preview_cannot_prove_no_individual_id(self):
        r=review();r['individual_id']={'status':'known','value':'不存在个体ID','evidence':['fields']}
        with self.assertRaises(ValueError):validate_review(r,self.config,{'card':{},'fields':{}})
    def test_refresh_rechecks_same_ids_without_new_recommendations(self):
        state,first=run(self.config,None,'2026-10-05',FakeHub(8),FakeReviewer())
        hub=FakeHub(8);state,refreshed=refresh_existing(self.config,state,first,hub,FakeReviewer())
        self.assertEqual(set(hub.read),set(r['id'] for r in first['datasets']))
        self.assertEqual(len(hub.read),3);self.assertEqual(refreshed['reviewed_this_run'],3)
    def test_missing_preview_does_not_mean_gated_access(self):
        r=review();r['application']='需要申请访问权限才能用于个体行为研究。'
        with self.assertRaises(ValueError):validate_review(r,self.config,{'metadata':{'text':'{"gated": false}'},'card':{'text':'Public structure matrices'}})
        r=review();r['evidence']=['invented']
        with self.assertRaises(ValueError):validate_review(r,self.config,{'card':{}})
    def test_all_failed_reviews_do_not_publish_empty_day(self):
        class Failed(FakeReviewer):
            def review(self,*args):raise ValueError('broken JSON')
        with self.assertRaises(RuntimeError):run(self.config,None,'2026-10-05',FakeHub(),Failed())
    def test_markdown_contains_evidence_and_unknowns(self):
        _,r=run(self.config,None,'2026-10-05',FakeHub(1),FakeReviewer())
        text=markdown(r);self.assertIn('用途（推断）',text);self.assertIn('证据 card',text);self.assertIn('未知',text)
if __name__=='__main__':unittest.main()
