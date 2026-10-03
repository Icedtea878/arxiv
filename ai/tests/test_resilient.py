import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from langchain_core.runnables import RunnableLambda
from resilient import invoke_summary, parse_summary, load_cache, save_cache
from structure import Structure
import enhance

FIELDS = {name: "valid summary" for name in Structure.model_fields}


class FakeModel(RunnableLambda):
    def with_structured_output(self, *args, **kwargs):
        return self


class ResilientSummaryTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"OPENAI_API_KEY": "test-only-key", "OPENAI_BASE_URL": "https://example.invalid/v1"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_empty_tool_result_uses_valid_raw_json_without_another_request(self):
        chain = Mock()
        chain.invoke.return_value = {"parsed": None, "raw": SimpleNamespace(content="```json\n" + json.dumps(FIELDS) + "\n```")}
        fallback = Mock()
        self.assertEqual(invoke_summary(chain, fallback, {}).model_dump(), FIELDS)
        fallback.invoke.assert_not_called()

    @patch("resilient.time.sleep")
    def test_empty_structured_results_use_plain_json_fallback(self, _sleep):
        chain = Mock(); chain.invoke.return_value = None
        fallback = Mock(); fallback.invoke.return_value = SimpleNamespace(content=json.dumps(FIELDS))
        self.assertEqual(invoke_summary(chain, fallback, {}).model_dump(), FIELDS)
        self.assertEqual(chain.invoke.call_count, 3)
        fallback.invoke.assert_called_once()

    def test_authentication_failure_does_not_retry(self):
        chain = Mock(); chain.invoke.side_effect = RuntimeError("401 Unauthorized")
        fallback = Mock()
        with self.assertRaises(RuntimeError):
            invoke_summary(chain, fallback, {})
        self.assertEqual(chain.invoke.call_count, 1)
        fallback.invoke.assert_not_called()

    def test_partial_batch_preserves_failed_paper_and_reuses_successes(self):
        items = [{"id": "1", "summary": "one"}, {"id": "2", "summary": "two"}]
        def result(_chain, item, _language, _fallback):
            if item["id"] == "2":
                raise ValueError("empty provider result")
            return {**item, "AI": FIELDS, "AI_status": "success"}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "summaries.jsonl"
            with patch("enhance.ChatOpenAI", return_value=FakeModel(lambda _: None)), patch("enhance.process_single_item", side_effect=result):
                papers = enhance.process_all_items(items, "model", "Chinese", 1, cache)
            self.assertEqual(len(papers), 2)
            self.assertEqual(papers[1]["AI_status"], "failed")
            self.assertNotIn("AI", papers[1])
            self.assertEqual(papers[1]["summary"], "two")
            self.assertEqual(len(load_cache(cache)), 1)
            with patch("enhance.ChatOpenAI", return_value=FakeModel(lambda _: None)), patch("enhance.process_single_item") as process:
                reused = enhance.process_all_items([{"id": "1", "summary": "one", "research_rank": 9}], "model", "Chinese", 1, cache)
            process.assert_not_called()
            self.assertEqual(reused[0]["research_rank"], 9)
            self.assertEqual(reused[0]["AI_status"], "success")

    def test_complete_provider_failure_still_fails_the_workflow(self):
        with patch("enhance.ChatOpenAI", return_value=FakeModel(lambda _: None)), patch("enhance.process_single_item", side_effect=ValueError("empty provider result")):
            with self.assertRaisesRegex(RuntimeError, "checkpoints were preserved"):
                enhance.process_all_items([{"id": "1", "summary": "one"}], "model", "Chinese", 1)

    def test_truncated_checkpoint_tail_does_not_discard_successes(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "summaries.jsonl"
            save_cache(cache, "success", FIELDS)
            with cache.open("a") as output: output.write('{"key":')
            self.assertEqual(load_cache(cache), {"success": FIELDS})
            save_cache(cache, "next", FIELDS)
            self.assertEqual(set(load_cache(cache)), {"success", "next"})


if __name__ == "__main__":
    unittest.main()
