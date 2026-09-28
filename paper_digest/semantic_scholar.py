"""Semantic Scholar Graph API로 인용수·저자 메타데이터 보강."""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

from .http_utils import request_with_retry
from .models import Paper

log = logging.getLogger(__name__)

BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
FIELDS = "citationCount,influentialCitationCount,venue,authors.name,authors.citationCount,authors.hIndex"


def enrich_papers(papers: List[Paper], api_key: Optional[str] = None) -> None:
    """배치 엔드포인트 1회 호출로 전체 논문을 보강. 실패해도 파이프라인은 계속 진행."""
    if not papers:
        return
    session = requests.Session()
    if api_key:
        session.headers["x-api-key"] = api_key
    try:
        resp = request_with_retry(
            session, "POST", BATCH_URL,
            params={"fields": FIELDS},
            json={"ids": [f"ARXIV:{p.arxiv_id}" for p in papers]},
            # 키 없이 쓰면 공용 rate limit에 자주 걸리므로 재시도를 넉넉히
            max_retries=6, base_delay=3.0,
        )
    except Exception:
        log.exception("Semantic Scholar 조회 실패 — 메타데이터 없이 진행")
        return

    for paper, data in zip(papers, resp.json()):
        if not data:  # 아직 S2에 색인되지 않은 신규 논문
            log.info("S2 미색인: %s", paper.arxiv_id)
            continue
        paper.citation_count = data.get("citationCount")
        paper.influential_citation_count = data.get("influentialCitationCount")
        paper.venue = data.get("venue") or None
        authors = data.get("authors") or []
        cites = [a["citationCount"] for a in authors if a.get("citationCount") is not None]
        hidx = [a["hIndex"] for a in authors if a.get("hIndex") is not None]
        paper.max_author_citations = max(cites) if cites else None
        paper.max_author_hindex = max(hidx) if hidx else None
