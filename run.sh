#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python ai/research_config.py
# The same profile controls local crawling and keyword selection.
export CATEGORIES="$(python -c 'from ai.research_config import load_config; print(",".join(load_config()["crawl"]["categories"]))')"
export MAX_PAPERS_PER_CATEGORY="$(python -c 'from ai.research_config import load_config; print(load_config()["crawl"]["per_category"])')"
export MAX_PAPERS_PER_DAY="$(python -c 'from ai.research_config import load_config; print(load_config()["crawl"]["shortlist"])')"
export RESEARCH_PROFILE="$(python -c 'import json; from ai.research_config import load_config; print(json.dumps(load_config()["keyword_profile"]))')"
today=$(date -u +%Y-%m-%d)
mkdir -p data
(cd daily_arxiv && scrapy crawl arxiv -O "../data/$today.jsonl")
if (cd daily_arxiv && python daily_arxiv/check_stats.py); then
  python daily_arxiv/select_papers.py --data "data/$today.jsonl"
  python ai/research_pipeline.py --data "data/$today.jsonl"
  ls data/*.jsonl | sed 's|data/||' > assets/file-list.txt
else
  code=$?
  if [ "$code" != 1 ]; then exit "$code"; fi
fi
