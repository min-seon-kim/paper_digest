"""설정 로딩: .env(비밀값) + config.yaml(동작 설정)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

load_dotenv(ENV_PATH)


def _env(name: str) -> Optional[str]:
    value = os.getenv(name, "").strip()
    return value or None


@dataclass
class Settings:
    categories: List[str]
    lookback_hours: int
    max_papers_per_day: int
    claude_model: str
    summarizer: str
    summary_source: str
    filter_topics: Dict[str, Dict[str, List[str]]]
    interest_keywords: List[str]
    category_icons: Dict[str, str]

    anthropic_api_key: Optional[str] = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    notion_token: Optional[str] = field(default_factory=lambda: _env("NOTION_TOKEN"))
    notion_database_id: Optional[str] = field(default_factory=lambda: _env("NOTION_DATABASE_ID"))
    notion_parent_page_id: Optional[str] = field(default_factory=lambda: _env("NOTION_PARENT_PAGE_ID"))
    notion_digest_parent_page_id: Optional[str] = field(
        default_factory=lambda: _env("NOTION_DIGEST_PARENT_PAGE_ID")
    )
    s2_api_key: Optional[str] = field(default_factory=lambda: _env("S2_API_KEY"))

    def icon_for(self, category: str) -> str:
        return self.category_icons.get(category, self.category_icons.get("default", "📄"))


def load_settings(path: Path = ROOT / "config.yaml") -> Settings:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings(
        categories=raw["categories"],
        lookback_hours=int(raw.get("lookback_hours", 24)),
        max_papers_per_day=int(raw.get("max_papers_per_day", 15)),
        claude_model=raw.get("claude_model", "claude-sonnet-5"),
        summarizer=raw.get("summarizer", "claude_code"),
        summary_source=raw.get("summary_source", "fulltext"),
        # 예전 형식(filter_groups: 그룹 → 패턴)도 주제 1개로 취급해 계속 지원
        filter_topics=raw.get("filter_topics") or {"Default": raw.get("filter_groups", {})},
        interest_keywords=raw.get("interest_keywords", []),
        category_icons=raw.get("category_icons", {}),
    )
