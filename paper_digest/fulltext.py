"""arXiv HTML 버전에서 논문 본문 텍스트를 추출. HTML이 없으면 None (초록으로 대체)."""
from __future__ import annotations

import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .http_utils import request_with_retry

log = logging.getLogger(__name__)

HTML_URL = "https://arxiv.org/html/{}"
# 방법론·실험을 다루기에 충분한 최소 분량. 이보다 짧으면 변환 실패로 보고 초록 사용
MIN_CHARS = 3000


def fetch_fulltext(arxiv_id: str) -> Optional[str]:
    session = requests.Session()
    session.headers["User-Agent"] = "paper-digest/1.0"
    try:
        resp = session.get(HTML_URL.format(arxiv_id), timeout=60)
        if resp.status_code == 404:
            log.info("HTML 전문 없음 (초록으로 요약): %s", arxiv_id)
            return None
        if resp.status_code != 200:
            resp = request_with_retry(session, "GET", HTML_URL.format(arxiv_id), timeout=60)
    except Exception:
        log.warning("HTML 전문 가져오기 실패 (초록으로 요약): %s", arxiv_id, exc_info=True)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    article = soup.find("article")
    if article is None:
        return None
    # 참고문헌·각주 번호·이미지 등 요약에 불필요한 부분 제거
    for sel in ["section.ltx_bibliography", "nav", "header", "footer", "img", "svg",
                "div.ltx_pagination", "span.ltx_note_mark", "script", "style"]:
        for tag in article.select(sel):
            tag.decompose()
    # 수식은 LaTeX 원문(alttext)으로 치환
    for m in article.find_all("math"):
        m.replace_with(f" ${m.get('alttext', '')}$ ")
    # 섹션 제목은 구분되도록 마크다운 헤더로
    for h in article.find_all(re.compile(r"^h[1-6]$")):
        h.insert_before("\n\n## ")
        h.insert_after("\n")

    text = article.get_text(" ")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    if len(text) < MIN_CHARS:
        return None
    log.info("HTML 전문 확보: %s (%d자)", arxiv_id, len(text))
    return text
