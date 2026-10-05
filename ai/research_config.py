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
class Models(Strict):
    triage: str = Field(min_length=1)
    reader: str = Field(min_length=1)
    judge: str = Field(min_length=1)
    base_url: str
    judge_base_url: str = ''
class Reading(Strict):
    max_fulltext_papers: int | None = Field(default=None, ge=1)
    chunk_chars: int = Field(default=24000, ge=4000, le=48000)
    max_revisions: int = Field(default=1, ge=0, le=1)
class Output(Strict):
    language: str = Field(min_length=1)
    brief_sentences: int = Field(ge=2, le=6)
    detail_words: int = Field(ge=200, le=3000)
    sections: list[str] = Field(min_length=1)
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
    models: Models
    reading: Reading
    output: Output

    @model_validator(mode='after')
    def valid(self):
        if self.version != 1 or set(self.grades) != set('ABCDE'):
            raise ValueError('version=1 and all ABCDE definitions required')
        if not self.directions or not all(re.fullmatch(r'[a-z][a-z0-9_]*', k) and v.strip() for k,v in self.directions.items()):
            raise ValueError('Direction IDs must be lowercase identifiers with descriptions')
        if not set(self.retain_grades) <= set('ABCDE') or len(set(self.retain_grades)) != len(self.retain_grades):
            raise ValueError('Invalid retained grades')
        if not all(re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]*', c) for c in self.crawl.categories):
            raise ValueError('Invalid arXiv categories')
        from urllib.parse import urlparse
        for url in [self.models.base_url, self.models.judge_base_url]:
            if url and (urlparse(url).scheme != 'https' or not urlparse(url).hostname):
                raise ValueError('Model base URLs must use HTTPS')
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
