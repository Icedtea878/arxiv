"""One versioned research profile for crawling, grading, reading and reports."""
import argparse
import json
import os
import re
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Crawl(Strict):
    categories: list[str] = Field(min_length=1)
    per_category: int = Field(ge=1, le=1000)
    shortlist: int = Field(ge=1, le=2000)
class Reading(Strict):
    max_fulltext_papers: int | None = Field(default=None, ge=1)
    chunk_chars: int = Field(default=24000, ge=4000, le=48000)
    max_revisions: int = Field(default=1, ge=0, le=1)
class Output(Strict):
    language: str = Field(min_length=1)
    brief_sentences: int = Field(ge=2, le=6)
    detail_words: int = Field(ge=200, le=3000)
    sections: list[str] = Field(min_length=1)
class DatasetSelection(Strict):
    enabled: bool = True
    daily_limit: int = Field(default=5, ge=1, le=10)
    review_limit: int = Field(default=20, ge=1, le=50)
    queries_per_day: int = Field(default=12, ge=1, le=30)
    results_per_query: int = Field(default=20, ge=2, le=50)
    card_chars: int = Field(default=12000, ge=2000, le=24000)
    candidate_limit: int = Field(default=2000, ge=100, le=5000)
    recheck_days: int = Field(default=30, ge=7, le=365)
    queries: dict[str,list[str]] = Field(default_factory=lambda: {
        'individual':['persona','personality','user simulation','human behavior'],
        'interaction':['dialogue','negotiation','theory-of-mind','sotopia'],
        'group':['cooperation','multi-agent','collective','group decision'],
        'society':['social network','opinion','social norm','community']})
    aliases: dict[str,str] = Field(default_factory=dict)
class ResearchConfig(Strict):
    version: int
    name: str = Field(min_length=1)
    research_goal: str = Field(min_length=1)
    directions: dict[str,str]
    questions: list[str] = Field(min_length=1)
    grades: dict[str,str]
    exclusions: list[str]
    examples: list[dict[str,str]]
    retain_grades: list[str] = Field(min_length=1)
    crawl: Crawl
    keyword_profile: dict
    reading: Reading
    output: Output
    datasets: DatasetSelection = Field(default_factory=DatasetSelection)

    @model_validator(mode='after')
    def valid(self):
        if self.version != 1 or set(self.grades) != set('ABCDE'):
            raise ValueError('version=1 and all ABCDE definitions required')
        if not self.directions or not all(re.fullmatch(r'[a-z][a-z0-9_]*', k) and v.strip() for k,v in self.directions.items()):
            raise ValueError('Direction IDs must be lowercase identifiers with descriptions')
        if not self.datasets.queries:raise ValueError('At least one dataset query direction is required')
        if not set(self.datasets.queries) <= set(self.directions):
            raise ValueError('Dataset query directions must exist in the research profile')
        if not all(terms and all(isinstance(t,str) and 0<len(t.strip())<=100 for t in terms) for terms in self.datasets.queries.values()):
            raise ValueError('Dataset queries must be nonempty short strings')
        if self.datasets.daily_limit>self.datasets.review_limit:
            raise ValueError('Dataset daily limit must not exceed review limit')
        if not set(self.retain_grades) <= set('ABCDE') or len(set(self.retain_grades)) != len(self.retain_grades):
            raise ValueError('Invalid retained grades')
        if not all(re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]*', c) for c in self.crawl.categories):
            raise ValueError('Invalid arXiv categories')
        # Reuse the established keyword validator, without environment overrides.
        import sys
        sys.path.insert(0, str(ROOT))
        from daily_arxiv.select_papers import validate_profile
        validate_profile(self.keyword_profile)
        return self

def load_config(path=None):
    path = Path(path or ROOT / 'research_config.json')
    return ResearchConfig.model_validate_json(path.read_text(encoding='utf-8')).model_dump()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path)
    parser.add_argument('--github-env',action='store_true')
    args=parser.parse_args()
    c=load_config(args.config)
    if args.github_env:
        values={'CATEGORIES':','.join(c['crawl']['categories']), 'MAX_PAPERS_PER_CATEGORY':str(c['crawl']['per_category']),
                'MAX_PAPERS_PER_DAY':str(c['crawl']['shortlist']), 'RESEARCH_PROFILE':json.dumps(c['keyword_profile'],ensure_ascii=False)}
        with open(os.environ['GITHUB_ENV'],'a',encoding='utf-8') as out:
            for key,value in values.items(): out.write(f'{key}={value}\n')
    print('Research configuration valid:',c['name'])
if __name__=='__main__': main()
