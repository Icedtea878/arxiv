"""Centralized model configuration. Single source of truth for model names.

Edit /models.json at the repo root to switch models. Any field can be
overridden by an environment variable (e.g. MODEL_TRIAGE, MODEL_READER,
OPENAI_BASE_URL, JUDGE_BASE_URL).
"""
import json
import os
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "models.json"

VALID_ROLES = ("triage", "reader", "judge", "dataset", "crawler")


@lru_cache(maxsize=1)
def _load() -> dict:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_model(role: str) -> str:
    """Return the model name for a role.

    role: one of triage | reader | judge | dataset | crawler
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown model role: {role!r}. Valid: {VALID_ROLES}")
    cfg = _load()
    return os.getenv(f"MODEL_{role.upper()}") or cfg[role]


def get_base_url(role: str = "default") -> str:
    """Return the OpenAI-compatible base URL for a role.

    role: "default" or "judge"
    """
    cfg = _load()
    if role == "judge":
        return (
            os.getenv("JUDGE_BASE_URL")
            or cfg.get("judge_base_url")
            or cfg["base_url"]
        )
    return os.getenv("OPENAI_BASE_URL") or cfg["base_url"]
