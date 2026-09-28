"""arXiv API로 지정 카테고리의 최근 논문을 수집."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import List

import feedparser
import requests

from .http_utils import request_with_retry
from .models import Paper

log = logging.getLogger(__name__)

API_URL = "https://export.arxiv.org/api/query"
PAGE_SIZE = 200
MAX_PAGES = 25
# arXiv API 이용 수칙: 연속 요청 사이 3초 대기
REQUEST_INTERVAL = 3.0


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_entry(entry) -> Paper:
    raw_id = entry.id.rsplit("/abs/", 1)[-1]
    arxiv_id = re.sub(r"v\d+$", "", raw_id)
    pdf_url = next(
        (l.href for l in entry.get("links", []) if l.get("title") == "pdf"),
        f"https://arxiv.org/pdf/{arxiv_id}",
    )
    categories = [t["term"] for t in entry.get("tags", [])]
    primary = entry.get("arxiv_primary_category", {}).get("term") or (categories[0] if categories else "")
    return Paper(
        arxiv_id=arxiv_id,
        title=_clean(entry.title),
        abstract=_clean(entry.summary),
        authors=[a.name for a in entry.get("authors", [])],
        published=datetime(*entry.published_parsed[:6], tzinfo=timezone.utc),
        categories=categories,
        primary_category=primary,
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=pdf_url.replace("http://", "https://"),
    )


def fetch_recent_papers(categories: List[str], lookback_hours: int) -> List[Paper]:
    """제출일 내림차순으로 페이지를 넘기며 cutoff 이전 논문이 나오면 중단.

    arXiv는 제출 → 발표(announce)까지 지연이 있어 '지금'부터 N시간을 세면 아직 발표 전인
    구간만 보게 된다. 그래서 cutoff는 API가 돌려준 '가장 최신 논문의 제출 시각' 기준으로 잡는다.
    """
    cutoff = None
    query = " OR ".join(f"cat:{c}" for c in categories)
    session = requests.Session()
    session.headers["User-Agent"] = "paper-digest/1.0 (daily arXiv digest to Notion)"

    papers: dict = {}
    for page in range(MAX_PAGES):
        if page:
            time.sleep(REQUEST_INTERVAL)
        resp = request_with_retry(
            session, "GET", API_URL,
            params={
                "search_query": query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": page * PAGE_SIZE,
                "max_results": PAGE_SIZE,
            },
            timeout=60,
        )
        feed = feedparser.parse(resp.text)
        if not feed.entries:
            break

        reached_cutoff = False
        if cutoff is None:
            newest = datetime(*feed.entries[0].published_parsed[:6], tzinfo=timezone.utc)
            cutoff = newest - timedelta(hours=lookback_hours)
            log.info("최신 논문 제출 시각 %s → %s 이후 제출분 수집", newest.isoformat(), cutoff.isoformat())
        for entry in feed.entries:
            try:
                paper = _parse_entry(entry)
            except Exception:
                log.exception("arXiv 항목 파싱 실패: %s", entry.get("id"))
                continue
            if paper.published < cutoff:
                reached_cutoff = True
                continue
            papers.setdefault(paper.arxiv_id, paper)
        log.info("arXiv 페이지 %d: %d건 (누적 %d건)", page + 1, len(feed.entries), len(papers))
        if reached_cutoff:
            break
    else:
        log.warning("최대 페이지(%d) 도달 — 일부 논문이 누락됐을 수 있음", MAX_PAGES)

    return list(papers.values())
