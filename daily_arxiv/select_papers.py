"""Prioritize Social World Model candidates before paid AI processing.

Keyword ranking is a discovery aid, not a semantic relevance judgment.
The crawler still has a per-category candidate limit; this does not search
the complete arXiv archive.
"""
import argparse
import json
import os
import re
from pathlib import Path

TOPICS = {
    "social world model": 12, "social simulation": 8,
    "social reasoning": 8, "theory of mind": 8,
    "mental state": 6, "social interaction": 6,
    "social intelligence": 6, "social cognition": 6,
    "human behavior": 5, "human behaviour": 5,
    "belief tracking": 5, "belief transition": 5,
    "agent based simulation": 5, "multi agent": 3,
    "multiagent": 3, "persona": 3, "personality": 3,
    "social network": 3, "world model": 2,
}


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def rank(paper):
    title = " " + normalize(paper.get("title", "")) + " "
    text = title + normalize(paper.get("summary", "")) + " "
    patterns = {term: r"\b" + re.escape(term) + r"s?\b" for term in TOPICS}
    matches = [term for term, pattern in patterns.items() if re.search(pattern, text)]
    score = sum(TOPICS[term] * (2 if re.search(patterns[term], title) else 1) for term in matches)
    return score, matches


def select(papers, limit):
    if limit < 1:
        raise ValueError("MAX_PAPERS_PER_DAY must be positive")
    unique = {}
    for paper in papers:
        paper_id = re.sub(r"v\d+$", "", paper.get("id", ""))
        if not paper_id:
            raise ValueError("Paper is missing its arXiv ID")
        if paper_id not in unique:
            score, matches = rank(paper)
            unique[paper_id] = {**paper, "research_score": score, "research_matches": matches}
    return sorted(unique.values(), key=lambda paper: -paper["research_score"])[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=int(os.getenv("MAX_PAPERS_PER_DAY", "200")))
    args = parser.parse_args()
    papers = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    selected = select(papers, args.limit)
    args.data.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in selected))
    matched = sum(p["research_score"] > 0 for p in selected)
    print(f"Social World Model selection: {len(papers)} candidates → {len(selected)} papers; "
          f"{matched} have topic keyword matches (heuristic, not guaranteed relevance).")


if __name__ == "__main__":
    main()
