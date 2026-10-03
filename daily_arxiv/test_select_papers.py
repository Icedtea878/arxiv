import unittest

from daily_arxiv.select_papers import rank, select


class SelectionTests(unittest.TestCase):
    def test_social_world_models_rank_before_generic_vision(self):
        papers = [
            {"id": "2601.00001v1", "title": "Efficient vision", "summary": "image recognition"},
            {"id": "2601.00002v1", "title": "Social World Models", "summary": "theory of mind"},
            {"id": "2601.00003", "title": "Multi-agent social simulation", "summary": "human behavior"},
        ]
        selected = select(papers, 2)
        self.assertEqual([p["id"] for p in selected], ["2601.00002v1", "2601.00003"])
        self.assertIn("social world model", selected[0]["research_matches"])

    def test_cross_listed_versions_are_not_counted_twice(self):
        papers = [{"id": "2601.00001v1", "title": "Social reasoning"},
                  {"id": "2601.00001v2", "title": "Social reasoning"}]
        self.assertEqual(len(select(papers, 200)), 1)

    def test_word_boundaries_and_title_weight(self):
        self.assertEqual(rank({"title": "Impersonation detection"})[0], 0)
        self.assertGreater(rank({"title": "Theory-of-mind"})[0],
                           rank({"summary": "theory of mind"})[0])

    def test_unmatched_papers_fill_remaining_slots(self):
        selected = select([{"id": "2601.00001", "title": "Vision"}], 200)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["research_score"], 0)
        self.assertEqual(select([], 200), [])

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            select([], 0)


if __name__ == "__main__":
    unittest.main()
