"""One real paper, full-text retrieval, reader and judge; never publishes daily data."""
import json
from pathlib import Path
from research_config import load_config, ROOT
from research_pipeline import run, reports_markdown, write_json

config=load_config()
paper=json.loads((ROOT/'ai/tests/fixtures/reading_paper.json').read_text(encoding='utf-8'))
retained,report=run([paper],config,ROOT/'.ai-cache/research')
out=ROOT/'smoke-reports';out.mkdir(exist_ok=True)
write_json(out/'report.json',report)
brief,detail=reports_markdown(retained,report,config,'sample')
(out/'brief.md').write_text(brief,encoding='utf-8');(out/'detailed.md').write_text(detail,encoding='utf-8')
print('Smoke results:',{k:report[k] for k in ['assessed','retained','reviewed','pending','grades','model_calls','cache_hits','usage']})
decision=report['decisions'][0]['review']
if decision['status'] not in ['reviewed','pending_review'] or not decision.get('analysis') or not decision.get('judgments'):
    raise RuntimeError('Real full-text analysis or judge did not execute; inspect smoke report')
print('Full-text reading, source validation, independent judge and both reports executed. Final grade/status:',decision['grade'],decision['status'])
