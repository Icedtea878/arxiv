"""Recover JSON responses and persist successful summaries between runs."""
import hashlib
import json
import time
from pathlib import Path
from structure import Structure


def parse_summary(response):
    if isinstance(response, Structure):
        parsed = response
    elif isinstance(response, dict) and "parsed" in response:
        if response["parsed"] is not None:
            return parse_summary(response["parsed"])
        return parse_summary(response.get("raw"))
    else:
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "\n".join(block.get("text", "") for block in content if isinstance(block, dict))
        if not isinstance(content, str):
            raise ValueError("provider returned an empty structured response")
        decoder = json.JSONDecoder()
        for offset, character in enumerate(content):
            if character != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(content[offset:])
                parsed = Structure.model_validate(payload)
                break
            except (ValueError, TypeError):
                continue
        else:
            raise ValueError("provider response did not contain the five summary fields")
    if not all(getattr(parsed, field).strip() for field in Structure.model_fields):
        raise ValueError("provider returned empty summary fields")
    return parsed


def invoke_summary(chain, fallback_chain, values):
    last_error = None
    for attempt in range(3):
        try:
            return parse_summary(chain.invoke(values))
        except Exception as error:
            last_error = error
            if fatal_provider_error(error):
                raise
            if attempt < 2:
                time.sleep(2 ** attempt)
    if fallback_chain is not None:
        try:
            return parse_summary(fallback_chain.invoke(values))
        except Exception as error:
            last_error = error
    raise RuntimeError(f"provider summary request failed after retries: {last_error}") from last_error


def fatal_provider_error(error):
    while error is not None:
        status = getattr(error, "status_code", None)
        text = str(error).lower()
        if status in (401, 403) or any(term in text for term in
            ("unauthorized", "invalid api key", "insufficient balance", "insufficient_balance", "insufficient_quota")):
            return True
        error = error.__cause__
    return False


def cache_key(item, model, language, base_url, prompts):
    content = json.dumps([item.get("summary", ""), model, language, base_url, prompts], ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()


def load_cache(path):
    cache = {}
    if path is not None and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                cache[record["key"]] = parse_summary(json.dumps(record["AI"])).model_dump()
            except (ValueError, KeyError, TypeError):
                continue
    return cache


def save_cache(path, key, summary):
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as previous:
            previous.seek(-1, 2)
            needs_newline = previous.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as output:
        if needs_newline:
            output.write("\n")
        output.write(json.dumps({"key": key, "AI": summary}, ensure_ascii=False) + "\n")
        output.flush()
