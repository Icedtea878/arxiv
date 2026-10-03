"""Rank method and dataset papers without making LLM requests."""
import argparse
import json
import os
import re
import unicodedata
from pathlib import Path

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "research_profile.json"
GROUPS = {"release", "simulation", "individual_history", "longitudinal", "personality_state", "behavior_prediction"}
REVIEW_TERMS = {
    "真人数据": ["participants", "human subjects", "human-human", "real-world conversations", "real users"],
    "稳定个体 ID": ["participant id", "user id", "subject id", "individual identifier", "person-level", "individual-level"],
    "时间信息": ["longitudinal", "timestamp", "repeated measures", "experience sampling", "daily diary", "multi-session", "temporal"],
    "可留出的行为标签": ["behavioral traces", "human choices", "next-action prediction", "response prediction", "preference prediction", "decision-making", "held-out", "test split"],
}


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def matches(text, term):
    # Hyphens and Unicode dashes share one spelling; plurals are accepted.
    return bool(re.search(r"\b" + re.escape(normalize(term)) + r"s?\b", text))


def name_matches(text, name):
    # NFKC maps E² to E2. Optional spaces accept compact and hyphenated names.
    compact = normalize(name).replace(" ", "")
    return bool(re.search(r"\b" + r"\s*".join(map(re.escape, compact)) + r"\b", text))


def load_profile():
    raw = os.getenv("RESEARCH_PROFILE", "").strip()
    profile = json.loads(raw) if raw else json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("RESEARCH_PROFILE must be a JSON object")
    if set(profile.get("groups", {})) != GROUPS:
        raise ValueError("RESEARCH_PROFILE groups must include: " + ", ".join(sorted(GROUPS)))
    for name, terms in profile["groups"].items():
        if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and normalize(t) for t in terms):
            raise ValueError(f"Invalid keyword group: {name}")
    if not isinstance(profile.get("method_keywords"), dict) or not profile["method_keywords"]:
        raise ValueError("method_keywords must be a nonempty object")
    for term, weight in profile["method_keywords"].items():
        if not normalize(term) or not isinstance(weight, (int, float)) or weight < 0:
            raise ValueError(f"Invalid method keyword weight: {term}")
    for rule in profile["combination_rules"]:
        if not rule["groups"] or not set(rule["groups"]) <= GROUPS or rule["score"] < 0:
            raise ValueError("Invalid dataset combination rule")
    for key in ["title_multiplier", "method_min_score", "dataset_name_score", "dataset_title_bonus"]:
        if not isinstance(profile[key], (int, float)) or profile[key] < 0:
            raise ValueError(f"Invalid nonnegative score: {key}")
    for key in ["dataset_names", "ambiguous_names"]:
        if not isinstance(profile[key], list) or not all(isinstance(t, str) and normalize(t) for t in profile[key]):
            raise ValueError(f"Invalid dataset name list: {key}")
    return profile


def evaluate(paper, profile):
    title = normalize(paper.get("title", ""))
    abstract = normalize(paper.get("summary", ""))
    text = title + " " + abstract
    terms = [term for term in profile["method_keywords"] if matches(text, term)]
    method_score = sum(profile["method_keywords"][term] *
                       (profile["title_multiplier"] if matches(title, term) else 1) for term in terms)
    hits = {group: [term for term in group_terms if matches(text, term)]
            for group, group_terms in profile["groups"].items()}
    # Take the highest eligible combination once, never add several tiers.
    rules = [rule for rule in profile["combination_rules"] if all(hits[g] for g in rule["groups"])]
    best_rule = max(rules, key=lambda rule: rule["score"], default=None)
    abstract_context = any(matches(abstract, term) for group in GROUPS - {"release"}
                           for term in profile["groups"][group])
    ambiguous = {normalize(name).replace(" ", "") for name in profile["ambiguous_names"]}
    names = []
    for name in profile["dataset_names"]:
        if not name_matches(text, name):
            continue
        if normalize(name).replace(" ", "") in ambiguous and (not hits["release"] or not abstract_context):
            continue
        names.append(name)
    # All generic release words combined earn at most one point, including
    # title mentions. They cannot qualify a paper for the dataset board alone.
    dataset_score = int(bool(hits["release"])) + (best_rule["score"] if best_rule else 0)
    dataset_score += profile["dataset_name_score"] if names else 0
    is_dataset = bool(best_rule or names)
    title_relevant = any(matches(title, term) for group in GROUPS - {"release"}
                         for term in profile["groups"][group]) or any(name_matches(title, name) for name in names)
    if is_dataset and title_relevant:
        dataset_score += profile["dataset_title_bonus"]
    checks = [{"question": question, "status": "待人工核验",
               "abstract_hints": [term for term in keywords if matches(abstract, term)]}
              for question, keywords in REVIEW_TERMS.items()]
    return {
        **paper,
        "research_method_score": method_score,
        "research_dataset_score": dataset_score,
        "research_score": method_score + dataset_score,
        "research_matches": terms,
        "dataset_group_matches": hits,
        "dataset_combination": best_rule,
        "tracked_datasets": names,
        "dataset_eligible": is_dataset,
        "dataset_manual_checks": checks,
        "research_boards": [],
        "research_board_ranks": {},
    }


def select_rankings(papers, limit=200, profile=None):
    if limit < 1:
        raise ValueError("MAX_PAPERS_PER_DAY must be positive")
    profile = profile if profile is not None else load_profile()
    unique = {}
    for paper in papers:
        key = re.sub(r"v\d+$", "", paper.get("id", ""))
        if not key:
            raise ValueError("Paper is missing its arXiv ID")
        if key not in unique:
            unique[key] = evaluate(paper, profile)
    candidates = list(unique.values())
    selected = sorted(candidates, key=lambda p: (-p["research_score"], p["id"]))[:limit]
    for position, paper in enumerate(selected, 1):
        paper["research_rank"] = position
    methods = sorted((p for p in selected if p["research_method_score"] >= profile["method_min_score"]),
                     key=lambda p: (-p["research_method_score"], p["id"]))
    datasets = sorted((p for p in selected if p["dataset_eligible"]),
                      key=lambda p: (-p["research_dataset_score"], p["id"]))
    boards = {"methods": methods, "datasets": datasets}
    for board, entries in boards.items():
        for position, paper in enumerate(entries, 1):
            paper["research_boards"].append(board)
            paper["research_board_ranks"][board] = position
    return selected, boards, candidates


def write_reports(data_path, boards, candidate_count, selected):
    payload = {"candidate_count": candidate_count, "selected": selected, "methods": boards["methods"], "datasets": boards["datasets"],
               "note": "关键词排序，不是AI相关性判定；真人、个体ID、时间与行为标签均需人工核验。"}
    data_path.with_name(data_path.stem + "_rankings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# {data_path.stem} 研究论文排序", "", f"去重候选：{candidate_count} 篇；收录前 {len(selected)} 篇。方法/数据集标签可重叠，AI摘要只生成一次。", "",
             "## 总排名", "", "| 排名 | 论文 | 总分 |", "|---|---|---|"]
    for paper in selected:
        title = paper["title"].replace("\n", " ").replace("|", "\\|")
        lines.append(f"| {paper['research_rank']} | {title} | {paper['research_score']} |")
    lines.append("")
    for board, title in [("methods", "方法论文榜"), ("datasets", "数据集论文榜")]:
        lines.extend(["## " + title, ""])
        if not boards[board]:
            lines.extend(["前200篇中没有命中该榜规则的论文。", ""])
        for paper in boards[board]:
            score = paper["research_method_score"] if board == "methods" else paper["research_dataset_score"]
            paper_title = paper["title"].replace("\n", " ")
            lines.extend([f"### {paper['research_board_ranks'][board]}. {paper_title}", "",
                          f"https://arxiv.org/abs/{paper['id']} · 得分 {score}", "",
                          "关键词：" + ", ".join(paper["research_matches"] or ["无方法关键词"]), ""])
            if board == "datasets":
                lines.extend(["组合规则：" + (paper["dataset_combination"]["label"] if paper["dataset_combination"] else "数据集名称追踪"),
                              "追踪名称：" + ", ".join(paper["tracked_datasets"] or ["无"]), ""])
                for check in paper["dataset_manual_checks"]:
                    hints = ", ".join(check["abstract_hints"]) or "无明确关键词提示"
                    lines.append(f"- [ ] {check['question']}：待人工核验（摘要提示：{hints}）")
                lines.append("")
    data_path.with_name(data_path.stem + "_rankings.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=int(os.getenv("MAX_PAPERS_PER_DAY", "200")))
    args = parser.parse_args()
    papers = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected, boards, candidates = select_rankings(papers, args.limit)
    args.data.with_name(args.data.stem + "_candidates.jsonl").write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in candidates), encoding="utf-8")
    args.data.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in selected), encoding="utf-8")
    write_reports(args.data, boards, len(candidates), selected)
    print(f"Research rankings: {len(candidates)} unique candidates → {len(boards['methods'])} method papers, "
          f"{len(boards['datasets'])} dataset papers; {len(selected)} unique papers for AI.")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"has_selected={'true' if selected else 'false'}\n")
            output.write(f"selected_count={len(selected)}\n")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(args.data.with_name(args.data.stem + "_rankings.md").read_text(encoding="utf-8") + "\n")


if __name__ == "__main__":
    main()
