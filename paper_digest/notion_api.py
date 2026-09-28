"""Notion REST API 래퍼 (API 버전 2025-09-03, data source 기반)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set

import requests

from .http_utils import request_with_retry
from .models import Paper, PaperSummary, ProcessedPaper

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
TEXT_LIMIT = 2000  # rich_text 한 조각의 최대 길이

# 데이터베이스 속성 이름
P_TITLE = "제목"
P_AUTHORS = "저자"
P_DATE = "발행일"
P_CATEGORY = "카테고리"
P_KEYWORDS = "키워드"
P_RELEVANCE = "관련도"
P_ARXIV = "arXiv"
P_PDF = "PDF"
P_CITATIONS = "인용수"
P_AUTHOR_CITES = "저자 최대 인용수"
P_ONE_LINER = "한 줄 요약"
P_TOPIC = "주제"

TOPIC_COLORS = ["red", "green", "purple", "blue", "orange", "pink", "brown", "yellow"]

RELEVANCE_OPTIONS = [
    ("5 · 매우 높음", "red"),
    ("4 · 높음", "orange"),
    ("3 · 보통", "yellow"),
    ("2 · 낮음", "blue"),
    ("1 · 무관", "gray"),
]
RELEVANCE_EMOJI = {5: "🔥", 4: "⭐", 3: "👍", 2: "🙂", 1: "💤"}


def relevance_label(score: int) -> str:
    return RELEVANCE_OPTIONS[5 - score][0]


def database_properties_schema() -> Dict[str, Any]:
    return {
        P_TITLE: {"title": {}},
        P_ONE_LINER: {"rich_text": {}},
        P_RELEVANCE: {"select": {"options": [{"name": n, "color": c} for n, c in RELEVANCE_OPTIONS]}},
        P_TOPIC: {"multi_select": {"options": []}},
        P_AUTHORS: {"rich_text": {}},
        P_DATE: {"date": {}},
        P_CATEGORY: {"multi_select": {"options": []}},
        P_KEYWORDS: {"multi_select": {"options": []}},
        P_ARXIV: {"url": {}},
        P_PDF: {"url": {}},
        P_CITATIONS: {"number": {"format": "number"}},
        P_AUTHOR_CITES: {"number": {"format": "number_with_commas"}},
    }


# ---------- rich text / block 헬퍼 ----------

def text(content: str, *, url: Optional[str] = None, bold: bool = False,
         color: str = "default", italic: bool = False) -> List[Dict[str, Any]]:
    """2000자 제한을 넘으면 여러 조각으로 나눈다."""
    chunks = [content[i:i + TEXT_LIMIT] for i in range(0, len(content), TEXT_LIMIT)] or [""]
    out = []
    for chunk in chunks:
        item: Dict[str, Any] = {"type": "text", "text": {"content": chunk}}
        if url:
            item["text"]["link"] = {"url": url}
        if bold or italic or color != "default":
            item["annotations"] = {"bold": bold, "italic": italic, "color": color}
        out.append(item)
    return out


def block(kind: str, rich_text: List[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    return {"object": "block", "type": kind, kind: {"rich_text": rich_text, **extra}}


def heading2(title: str) -> Dict[str, Any]:
    return block("heading_2", text(title))


def bullets(items: Iterable[str]) -> List[Dict[str, Any]]:
    return [block("bulleted_list_item", text(i)) for i in items]


def _tag(name: str) -> str:
    # multi_select 옵션명에는 쉼표 불가, 최대 100자
    return name.replace(",", " ").strip()[:100]


# ---------- 클라이언트 ----------

class NotionClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })
        self._title_cache: Dict[str, str] = {}

    def _call(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        # Notion 평균 제한은 초당 3회 — 429 시 Retry-After를 따라 재시도
        try:
            resp = request_with_retry(self.session, method, f"{API}{path}", **kwargs)
        except requests.HTTPError as exc:
            body = exc.response.text[:500] if exc.response is not None else ""
            raise RuntimeError(f"Notion API 오류 {method} {path}: {body}") from exc
        return resp.json()

    # --- 데이터베이스 ---

    def create_database(self, parent_page_id: str, title: str) -> Dict[str, Any]:
        return self._call("POST", "/databases", json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": text(title),
            "icon": {"type": "emoji", "emoji": "📚"},
            "initial_data_source": {"properties": database_properties_schema()},
        })

    def get_database(self, database_id: str) -> Dict[str, Any]:
        return self._call("GET", f"/databases/{database_id}")

    def data_source_id(self, database_id: str) -> str:
        sources = self.get_database(database_id).get("data_sources", [])
        if not sources:
            raise RuntimeError("데이터베이스에 data source가 없습니다. NOTION_DATABASE_ID를 확인하세요.")
        return sources[0]["id"]

    def title_property(self, data_source_id: str) -> str:
        """기존 DB의 제목 속성 이름이 '제목'이 아닐 수 있으므로(예: 'Name') 실제 이름을 찾는다."""
        if data_source_id not in self._title_cache:
            props = self._call("GET", f"/data_sources/{data_source_id}").get("properties", {})
            self._title_cache[data_source_id] = next(
                (k for k, v in props.items() if v.get("type") == "title"), P_TITLE)
        return self._title_cache[data_source_id]

    def ensure_properties(self, data_source_id: str) -> List[str]:
        """스키마에 없는 속성을 추가하고 추가된 이름 목록을 반환 (제목 속성은 건드리지 않음)."""
        props = self._call("GET", f"/data_sources/{data_source_id}").get("properties", {})
        missing = {k: v for k, v in database_properties_schema().items()
                   if k not in props and "title" not in v}
        if missing:
            self._call("PATCH", f"/data_sources/{data_source_id}", json={"properties": missing})
        return list(missing)

    def database_parent_page_id(self, database_id: str) -> Optional[str]:
        parent = self.get_database(database_id).get("parent", {})
        return parent.get("page_id")

    def existing_arxiv_urls(self, data_source_id: str, since: date) -> Set[str]:
        """발행일이 since 이후인 페이지들의 arXiv URL 집합 (중복 체크용)."""
        urls: Set[str] = set()
        payload: Dict[str, Any] = {
            "filter": {"property": P_DATE, "date": {"on_or_after": since.isoformat()}},
            "page_size": 100,
        }
        while True:
            data = self._call("POST", f"/data_sources/{data_source_id}/query", json=payload)
            for page in data.get("results", []):
                url = page.get("properties", {}).get(P_ARXIV, {}).get("url")
                if url:
                    urls.add(url.rstrip("/"))
            if not data.get("has_more"):
                return urls
            payload["start_cursor"] = data["next_cursor"]

    # --- 페이지 ---

    def create_paper_page(self, data_source_id: str, paper: Paper, summary: PaperSummary,
                          icon: str) -> Dict[str, Any]:
        properties: Dict[str, Any] = {
            self.title_property(data_source_id): {"title": text(paper.title)},
            P_ONE_LINER: {"rich_text": text(summary.one_line_summary)},
            P_RELEVANCE: {"select": {"name": relevance_label(summary.relevance_score)}},
            P_TOPIC: {"multi_select": [{"name": _tag(t)} for t in paper.topics]},
            P_AUTHORS: {"rich_text": text(", ".join(paper.authors)[:TEXT_LIMIT])},
            P_DATE: {"date": {"start": paper.published.date().isoformat()}},
            P_CATEGORY: {"multi_select": [{"name": _tag(c)} for c in paper.categories]},
            P_KEYWORDS: {"multi_select": [{"name": _tag(k)} for k in dict.fromkeys(summary.keywords)]},
            P_ARXIV: {"url": paper.abs_url},
            P_PDF: {"url": paper.pdf_url},
            P_CITATIONS: {"number": paper.citation_count},
            P_AUTHOR_CITES: {"number": paper.max_author_citations},
        }
        return self._call("POST", "/pages", json={
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "icon": {"type": "emoji", "emoji": icon},
            "properties": properties,
            "children": paper_page_blocks(paper, summary),
        })

    def create_digest_page(self, parent_page_id: str, day: date,
                           items: List[ProcessedPaper], failed: int) -> Dict[str, Any]:
        return self._call("POST", "/pages", json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "icon": {"type": "emoji", "emoji": "📰"},
            "properties": {"title": {"title": text(f"오늘의 논문 다이제스트 · {day.isoformat()}")}},
            "children": digest_blocks(items, failed),
        })


# ---------- 페이지 본문 구성 ----------

def _meta_line(paper: Paper) -> List[Dict[str, Any]]:
    parts: List[Dict[str, Any]] = []
    parts += text("📅 ") + text(paper.published.date().isoformat())
    parts += text("   ·   📑 ") + text(paper.primary_category, bold=True)
    if paper.topics:
        parts += text("   ·   🏷️ ") + text(" / ".join(paper.topics), bold=True)
    if paper.citation_count is not None:
        parts += text(f"   ·   📈 인용 {paper.citation_count}회")
    if paper.max_author_hindex is not None:
        parts += text(f"   ·   👤 저자 최고 h-index {paper.max_author_hindex}")
    parts += text("   ·   ") + text("arXiv", url=paper.abs_url) + text(" / ") + text("PDF", url=paper.pdf_url)
    return parts


def paper_page_blocks(paper: Paper, summary: PaperSummary) -> List[Dict[str, Any]]:
    score = summary.relevance_score
    basis = "📖 본문 전체 기반 요약" if paper.fulltext else "📝 초록 기반 요약 (HTML 전문 없음)"
    blocks: List[Dict[str, Any]] = [
        block("callout", text(summary.one_line_summary, bold=True),
              icon={"type": "emoji", "emoji": "💡"}, color="yellow_background"),
        block("paragraph", _meta_line(paper)),
        block("quote", text(f"{RELEVANCE_EMOJI[score]} 관련도 {score}/5 — ", bold=True)
              + text(summary.relevance_reason), color="gray"),
        {"object": "block", "type": "divider", "divider": {}},
        heading2("🧩 문제 정의"),
        block("paragraph", text(summary.problem)),
        heading2("🎯 핵심 기여"),
        *[block("numbered_list_item", text(c)) for c in summary.key_contributions],
        heading2("🛠️ 방법론"),
        *bullets(summary.methodology),
        heading2("📊 주요 결과"),
        *bullets(summary.results),
        heading2("⚠️ 한계점"),
        *bullets(summary.limitations),
        {"object": "block", "type": "divider", "divider": {}},
        block("toggle", text("📄 원문 초록 (Abstract)", bold=True),
              children=[block("paragraph", text(paper.abstract))]),
        block("paragraph", text(f"{basis}  ·  👥 {', '.join(paper.authors)}"[:TEXT_LIMIT],
                                color="gray", italic=True)),
    ]
    return blocks


def digest_blocks(items: List[ProcessedPaper], failed: int) -> List[Dict[str, Any]]:
    items = sorted(items, key=lambda x: (x.summary.relevance_score, x.paper.filter_score), reverse=True)
    high = sum(1 for x in items if x.summary.relevance_score >= 4)
    headline = f"오늘 새로 정리된 논문 {len(items)}편 · 관련도 4 이상 {high}편"
    if failed:
        headline += f" · 처리 실패 {failed}편 (로그 확인)"
    blocks: List[Dict[str, Any]] = [
        block("callout", text(headline, bold=True), icon={"type": "emoji", "emoji": "🗞️"},
              color="blue_background"),
    ]
    if not items:
        blocks.append(block("paragraph", text("오늘은 조건에 맞는 신규 논문이 없습니다. ☕")))
        return blocks

    blocks.append(heading2("📋 관련도 순 목록"))
    for x in items:
        s = x.summary.relevance_score
        title_rt = [{"type": "mention", "mention": {"page": {"id": x.page_id}}}]
        blocks.append(block(
            "numbered_list_item",
            text(f"{RELEVANCE_EMOJI[s]} [{s}/5] ", bold=True) + title_rt,
            children=[
                block("paragraph", text(x.summary.one_line_summary)),
                block("paragraph", text("arXiv", url=x.paper.abs_url, color="blue")
                      + text("  ·  ") + text("PDF", url=x.paper.pdf_url, color="blue")
                      + text(f"  ·  {x.paper.primary_category}"
                             + (f"  ·  {' / '.join(x.paper.topics)}" if x.paper.topics else ""), color="gray")),
            ],
        ))
    return blocks
