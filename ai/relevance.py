"""Score title/abstract relevance; publish only strict threshold matches."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field
from runtime import build_chat_openai_kwargs
from resilient import fatal_provider_error

ROOT = Path(__file__).resolve().parents[1]
PROMPT = Path(__file__).with_name('relevance_prompt.txt').read_text(encoding='utf-8')


class Relevance(BaseModel):
    model_config = ConfigDict(extra='forbid')
    score: int = Field(strict=True, ge=0, le=100)
    directions: list[Literal['individual', 'interaction', 'group', 'society']]
    reason: str = Field(min_length=1, max_length=240)


def parse_response(response):
    content = getattr(response, 'content', response)
    if isinstance(content, list):
        content = '\n'.join(x.get('text', '') for x in content if isinstance(x, dict))
    if not isinstance(content, str):
        raise ValueError('Empty relevance response')
    decoder = json.JSONDecoder()
    for pos, char in enumerate(content):
        if char == '{':
            try:
                value, _ = decoder.raw_decode(content[pos:])
                result = Relevance.model_validate(value)
                if not result.reason.strip() or (result.score > 80 and not result.directions):
                    raise ValueError('Missing relevance evidence/direction')
                return result.model_dump()
            except (ValueError, TypeError):
                continue
    raise ValueError('Invalid relevance JSON or score')


def score_paper(llm, paper):
    values = json.dumps({'title': paper.get('title', ''), 'abstract': paper.get('summary', '')}, ensure_ascii=False)
    for attempt in range(3):
        try:
            response = llm.invoke([('system', PROMPT), ('human', values)])
            return parse_response(response), getattr(response, 'usage_metadata', None) or {}
        except Exception as error:
            if fatal_provider_error(error) or attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def cache_key(paper, model, base_url):
    payload = [paper.get('title', ''), paper.get('summary', ''), model, base_url, PROMPT]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def load_cache(path):
    cache = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
                cache[row['key']] = parse_response(json.dumps(row['relevance']))
            except (ValueError, TypeError, KeyError):
                continue
    return cache


def atomic_write(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def process(papers, llm, model, base_url, threshold, cache_path, report_path):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)
    results, failed = [], []
    cached = 0
    usage = {'input_tokens': 0, 'output_tokens': 0}
    for index, paper in enumerate(papers):
        key = cache_key(paper, model, base_url)
        try:
            if key in cache:
                relevance = cache[key]
                cached += 1
            else:
                relevance, tokens = score_paper(llm, paper)
                for name in usage:
                    usage[name] += tokens.get(name, 0) or 0
                # Prepend newline so an interrupted previous record cannot hide this one.
                with cache_path.open('a', encoding='utf-8') as output:
                    output.write('\n' + json.dumps({'key': key, 'relevance': relevance}, ensure_ascii=False) + '\n')
                    output.flush()
                cache[key] = relevance
            results.append({**paper, 'relevance': relevance, 'relevance_threshold': threshold, 'relevance_model': model})
            print(f"[{index + 1}/{len(papers)}] {paper.get('id')} relevance={relevance['score']}", flush=True)
        except Exception as error:
            # Do not turn provider errors into low relevance scores.
            failed.append({'id': paper.get('id'), 'error_type': type(error).__name__})
            print(f"[{index + 1}/{len(papers)}] {paper.get('id')} failed: {type(error).__name__}", flush=True)
            if fatal_provider_error(error):
                break
    retained = [p for p in results if p['relevance']['score'] > threshold]
    retained.sort(key=lambda p: (-p['relevance']['score'], p.get('research_rank') or float('inf'), str(p.get('id', ''))))
    report = {'candidate_count': len(papers), 'scored_count': len(results), 'retained_count': len(retained),
              'threshold': threshold, 'comparison': '>', 'cached_count': cached, 'model': model,
              'usage_this_run': usage, 'failed': failed,
              'scores': [{'id': p.get('id'), **p['relevance']} for p in results]}
    atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise RuntimeError(f'{len(failed)} relevance request(s) failed; checkpoints saved. Rerun to resume. No incomplete day published.')
    return retained, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    threshold = int(os.getenv('RELEVANCE_THRESHOLD', '80'))
    if not 0 <= threshold <= 100:
        raise ValueError('RELEVANCE_THRESHOLD must be 0–100')
    model = os.getenv('MODEL_NAME', 'MiniMax-M3')
    base_url = os.getenv('OPENAI_BASE_URL', 'https://api.minimax.cn/v1').rstrip('/')
    llm = ChatOpenAI(timeout=120, max_retries=1, **build_chat_openai_kwargs(model, base_url, os.getenv('OPENAI_API_KEY', '')))
    papers = [json.loads(line) for line in args.data.read_text(encoding='utf-8').splitlines() if line.strip()]
    prefix = args.data.with_suffix('')
    retained, report = process(papers, llm, model, base_url, threshold,
                               ROOT / '.ai-cache/relevance.jsonl', Path(str(prefix) + '_relevance_report.json'))
    atomic_write(Path(str(prefix) + '_relevance.jsonl'), ''.join(json.dumps(p, ensure_ascii=False) + '\n' for p in retained))
    summary = f"LLM 相关性：评估 {len(papers)} 篇，保留 {len(retained)} 篇（严格 > {threshold}/100）；缓存复用 {report['cached_count']} 篇。仅使用标题与原始摘要，不生成长总结。"
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(summary + '\n')


if __name__ == '__main__':
    main()
