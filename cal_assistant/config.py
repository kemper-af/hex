"""Config loader — reads config.yaml from the project root."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


# Project root = parent of this file's parent (cal_assistant/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Load config.yaml once per process."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {CONFIG_PATH}. "
            "Copy it from the template or check you're running from the project root."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_account_labels() -> list[str]:
    """Return the list of account labels defined in config (e.g. ['personal', 'work'])."""
    return list(load_config().get("accounts", {}).keys())


def project_path(*parts: str) -> Path:
    """Build a path relative to the project root."""
    return PROJECT_ROOT.joinpath(*parts)
