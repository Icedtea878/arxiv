import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from relevance import cache_key, parse_response, process


def result(score):
    return {'score': score, 'directions': ['individual'], 'reason': '依据摘要中的个体行为模拟任务。'}


class RelevanceTests(unittest.TestCase):
    def test_invalid_scores_and_missing_evidence(self):
        for score in [True, '85', 80.5, -1, 101]:
            with self.assertRaises(ValueError):
                parse_response(json.dumps(result(score)))
        with self.assertRaises(ValueError):
            parse_response('{"score":90,"directions":[],"reason":" "}')
        self.assertEqual(parse_response('```json\n' + json.dumps(result(81)) + '\n```')['score'], 81)

    def test_threshold_cache_and_changed_title(self):
        papers = [{'id': str(s), 'title': str(s), 'summary': 'abstract'} for s in [80, 81, 100]]
        with tempfile.TemporaryDirectory() as directory:
            cache, report = Path(directory)/'cache', Path(directory)/'report.json'
            with patch('relevance.score_paper', side_effect=[(result(s), {}) for s in [80, 81, 100]]) as score:
                kept, _ = process(papers, Mock(), 'model', 'url', 80, cache, report)
                self.assertEqual([p['id'] for p in kept], ['100', '81'])
                kept, stats = process(papers, Mock(), 'model', 'url', 90, cache, report)
                self.assertEqual([p['id'] for p in kept], ['100'])
                self.assertEqual(stats['cached_count'], 3)
                self.assertEqual(score.call_count, 3)
            self.assertNotEqual(cache_key(papers[0], 'model', 'url'), cache_key({**papers[0], 'title':'changed'}, 'model', 'url'))

    def test_failure_preserves_success_and_rerun_finishes(self):
        papers = [{'id': 'a', 'title':'a'}, {'id':'b','title':'b'}]
        with tempfile.TemporaryDirectory() as directory:
            cache, report = Path(directory)/'cache', Path(directory)/'report.json'
            with patch('relevance.score_paper', side_effect=[(result(90), {}), ValueError('bad response')]):
                with self.assertRaises(RuntimeError):
                    process(papers, Mock(), 'm', 'u', 80, cache, report)
            self.assertEqual(json.loads(report.read_text())['failed'][0]['id'], 'b')
            with patch('relevance.score_paper', return_value=(result(80), {})) as score:
                kept, stats = process(papers, Mock(), 'm', 'u', 80, cache, report)
                self.assertEqual([p['id'] for p in kept], ['a'])
                self.assertEqual(stats['cached_count'], 1)
                score.assert_called_once()

    def test_zero_retained_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('relevance.score_paper', return_value=(result(80), {})):
                kept, stats = process([{'id':'a'}], Mock(), 'm', 'u', 80, Path(directory)/'cache', Path(directory)/'report')
                self.assertEqual(kept, [])
                self.assertEqual(stats['scored_count'], 1)
