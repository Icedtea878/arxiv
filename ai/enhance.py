import os
import json
import sys
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
from queue import Queue
from threading import Lock
import dotenv
import argparse
from tqdm import tqdm

import langchain_core.exceptions
from langchain_openai import ChatOpenAI
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from structure import Structure
from content_filter import is_sensitive
from runtime import build_chat_openai_kwargs
from resilient import invoke_summary, fatal_provider_error, cache_key, load_cache, save_cache

if os.path.exists('.env'):
    dotenv.load_dotenv()
template = open("template.txt", "r").read()
system = open("system.txt", "r").read()

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, required=True, help="jsonline data file")
    parser.add_argument("--max_workers", type=int, default=1, help="Maximum number of parallel workers")
    return parser.parse_args()

def process_single_item(chain, item: Dict, language: str, fallback_chain=None) -> Dict:
    def check_github_code(content: str) -> Dict:
        """提取并验证 GitHub 链接"""
        code_info = {}

        # 1. 优先匹配 github.com/owner/repo 格式
        github_pattern = r"https?://github\.com/([a-zA-Z0-9-_]+)/([a-zA-Z0-9-_\.]+)"
        match = re.search(github_pattern, content)
        
        if match:
            owner, repo = match.groups()
            # 清理 repo 名称，去掉可能的 .git 后缀或末尾的标点
            repo = repo.rstrip(".git").rstrip(".,)")
            
            full_url = f"https://github.com/{owner}/{repo}"
            code_info["code_url"] = full_url
            
            # 尝试调用 GitHub API 获取信息
            github_token = os.environ.get("TOKEN_GITHUB")
            headers = {"Accept": "application/vnd.github.v3+json"}
            if github_token:
                headers["Authorization"] = f"token {github_token}"
            
            try:
                api_url = f"https://api.github.com/repos/{owner}/{repo}"
                resp = requests.get(api_url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    code_info["code_stars"] = data.get("stargazers_count", 0)
                    code_info["code_last_update"] = data.get("pushed_at", "")[:10]
            except Exception:
                # API 调用失败不影响主流程
                pass
            return code_info

        # 2. 如果没有 github.com，尝试匹配 github.io
        github_io_pattern = r"https?://[a-zA-Z0-9-_]+\.github\.io(?:/[a-zA-Z0-9-_\.]+)*"
        match_io = re.search(github_io_pattern, content)
        
        if match_io:
            url = match_io.group(0)
            # 清理末尾标点
            url = url.rstrip(".,)")
            code_info["code_url"] = url
            # github.io 不进行 star 和 update 判断
                
        return code_info

    # 检查 summary 字段
    if is_sensitive(item.get("summary", "")):
        return None

    # 检测代码可用性
    code_info = check_github_code(item.get("summary", ""))
    if code_info:
        item.update(code_info)

    """处理单个数据项"""
    response = invoke_summary(chain, fallback_chain, {
        "language": language, "content": item["summary"]
    })
    item["AI"] = response.model_dump()
    item["AI_status"] = "success"

    # Check the generated result once. Checking every field separately caused
    # six filter requests per paper and quickly hit the filter service limit.
    generated_text = "\n".join(str(value) for value in item.get("AI", {}).values())
    if is_sensitive(generated_text):
        return None
    return item

def process_all_items(data: List[Dict], model_name: str, language: str, max_workers: int, checkpoint_path=None) -> List[Dict]:
    """并行处理所有数据项"""
    llm = ChatOpenAI(
        timeout=90, max_retries=1,
        **build_chat_openai_kwargs(
            model_name=model_name,
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.minimax.cn/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
        )
    )

    print('Connect to:', model_name, file=sys.stderr)
    
    prompt_template = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system),
        HumanMessagePromptTemplate.from_template(template=template)
    ])

    chain = prompt_template | llm.with_structured_output(Structure, method="function_calling", include_raw=True)
    fallback_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system),
        HumanMessagePromptTemplate.from_template(template + "\nReturn only one JSON object with exactly these five nonempty string fields: tldr, motivation, method, result, conclusion. Do not use tools or add commentary.")
    ])
    fallback_chain = fallback_prompt | llm
    
    processed_data = [None] * len(data)
    processing_errors = []
    cache = load_cache(checkpoint_path)
    pending = []
    successes = 0
    for idx, item in enumerate(data):
        key = cache_key(item, model_name, language, os.environ.get("OPENAI_BASE_URL", ""), system + template + "resilient-v1")
        if key in cache:
            processed_data[idx] = {**item, "AI": cache[key], "AI_status": "success"}
            successes += 1
        else:
            pending.append((idx, item, key))
    print(f"Reusing {successes} cached summaries; {len(pending)} provider requests pending", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_item, chain, item, language, fallback_chain): (idx, item, key)
                   for idx, item, key in pending}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing items"):
            idx, item, key = futures[future]
            try:
                result = future.result()
                processed_data[idx] = result
                if result is not None:
                    successes += 1
                    save_cache(checkpoint_path, key, result["AI"])
            except Exception as error:
                print(f"AI summary failed for {item['id']}: {error}", file=sys.stderr)
                if fatal_provider_error(error):
                    for queued in futures:
                        queued.cancel()
                    raise RuntimeError("AI provider authentication or balance failure; successful checkpoints were preserved") from error
                processing_errors.append(item["id"])
                fallback = {k: v for k, v in item.items() if k != "AI"}
                fallback.update(AI_status="failed", AI_error="摘要生成失败，已保留英文原始摘要")
                processed_data[idx] = fallback
    if processing_errors:
        if successes == 0 or len(processing_errors) > max(1, len(data) // 10):
            raise RuntimeError(f"{len(processing_errors)} paper summaries failed; successful checkpoints were preserved")
        print(f"WARNING: {len(processing_errors)} summaries unavailable; preserving their original abstracts", file=sys.stderr)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as report:
            report.write(f"\n## AI 摘要处理\n成功或复用：{successes} 篇；摘要失败但保留原文：{len(processing_errors)} 篇。\n")
    return processed_data

def main():
    args = parse_args()
    model_name = os.environ.get("MODEL_NAME", "MiniMax-M3")
    language = os.environ.get("LANGUAGE", 'Chinese')

    target_file = args.data.replace('.jsonl', f'_AI_enhanced_{language}.jsonl')

    # 读取数据
    data = []
    with open(args.data, "r") as f:
        for line in f:
            data.append(json.loads(line))

    # 去重
    seen_ids = set()
    unique_data = []
    for item in data:
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            unique_data.append(item)

    data = unique_data
    print('Open:', args.data, file=sys.stderr)
    
    # 并行处理所有数据
    processed_data = process_all_items(
        data,
        model_name,
        language,
        args.max_workers,
        checkpoint_path=os.environ.get("AI_CHECKPOINT_PATH", "../.ai-cache/summaries.jsonl")
    )
    
    # 保存结果
    temporary_file = target_file + ".tmp"
    with open(temporary_file, "w") as f:
        for item in processed_data:
            if item is not None:
                f.write(json.dumps(item) + "\n")
    os.replace(temporary_file, target_file)

if __name__ == "__main__":
    main()
