import unittest

from daily_arxiv.select_papers import evaluate, load_profile, select_rankings


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile()

    def test_social_world_models_rank_before_generic_vision(self):
        papers = [
            {"id": "2601.00001v1", "title": "Efficient vision", "summary": "image recognition"},
            {"id": "2601.00002v1", "title": "Social World Models", "summary": "theory of mind"},
            {"id": "2601.00003", "title": "Multi-agent social simulation", "summary": "human behavior"},
        ]
        selected, boards, _ = select_rankings(papers, 2, self.profile)
        self.assertEqual([p["id"] for p in selected], ["2601.00002v1", "2601.00003"])
        self.assertIn("social world model", selected[0]["research_matches"])

    def test_cross_listed_versions_are_not_counted_twice(self):
        papers = [{"id": "2601.00001v1", "title": "Social reasoning"},
                  {"id": "2601.00001v2", "title": "Social reasoning"}]
        self.assertEqual(len(select_rankings(papers, profile=self.profile)[0]), 1)

    def test_word_boundaries_and_title_weight(self):
        self.assertEqual(evaluate({"title": "Impersonation detection"}, self.profile)["research_method_score"], 0)
        self.assertGreater(evaluate({"title": "Theory-of-mind"}, self.profile)["research_method_score"],
                           evaluate({"summary": "theory of mind"}, self.profile)["research_method_score"])

    def test_generic_papers_can_fill_200_without_entering_topic_boards(self):
        selected, boards, _ = select_rankings([{"id": "2601.00001", "title": "Vision dataset benchmark"}], profile=self.profile)
        self.assertEqual(len(selected), 1)
        self.assertEqual(boards, {"methods": [], "datasets": []})

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            select_rankings([], 0)

    def test_generic_dataset_words_earn_at_most_one_point(self):
        p = evaluate({"title": "Dataset benchmark corpus open data"}, self.profile)
        self.assertEqual(p["research_dataset_score"], 1)
        self.assertFalse(p["dataset_eligible"])

    def test_combination_scores_take_only_highest_tier(self):
        abstract = "We release a dataset for user simulation with individual-level user history and response prediction. Longitudinal repeated measures capture personality traits and mental state transitions."
        p = evaluate({"title": "New resources", "summary": abstract}, self.profile)
        self.assertEqual(p["dataset_combination"]["score"], 8)
        self.assertEqual(p["research_dataset_score"], 9)

    def test_combination_tiers_six_and_seven(self):
        for abstract, expected in [("A benchmark for human simulation", 6),
                                   ("A dataset with user history for next-action prediction", 7)]:
            p = evaluate({"summary": abstract}, self.profile)
            self.assertEqual(p["dataset_combination"]["score"], expected)

    def test_dataset_name_variants(self):
        for name in ["PERSONA E²", "PersonaE2", "Persona-E2", "Twin 2K 500", "BIG5 CHAT", "openESM"]:
            p = evaluate({"title": name}, self.profile)
            self.assertTrue(p["dataset_eligible"], name)

    def test_ambiguous_names_need_abstract_context(self):
        for name in ["OPeRA", "REALTALK"]:
            unrelated = evaluate({"title": name + " benchmark", "summary": "A computer vision task."}, self.profile)
            relevant = evaluate({"title": name + " benchmark", "summary": "Human-human dialogue with personality traits."}, self.profile)
            self.assertEqual(unrelated["tracked_datasets"], [])
            self.assertEqual(relevant["tracked_datasets"], [name])

    def test_global_top_limit_and_overlapping_tags_do_not_repeat_ai(self):
        papers = [{"id": f"2601.{i:05}", "title": "Mental state transition", "summary": "modeling methods"} for i in range(30)]
        papers += [{"id": f"2602.{i:05}", "title": "New resources", "summary": "A dataset with user history for response prediction"} for i in range(30)]
        papers.append({"id": "2603.00001", "title": "Mental state transition in human simulation dataset", "summary": "Persona simulation."})
        selected, boards, _ = select_rankings(papers, limit=50, profile=self.profile)
        self.assertEqual(len(selected), 50)
        self.assertEqual(len(boards["methods"]), 31)
        self.assertEqual(len(boards["datasets"]), 20)
        self.assertEqual(len(selected), len({p["id"] for p in selected}))
        self.assertEqual(len([p for p in selected if p["id"] == "2603.00001"]), 1)
        self.assertEqual(set(next(p for p in selected if p["id"] == "2603.00001")["research_boards"]), {"methods", "datasets"})


if __name__ == "__main__":
    unittest.main()
