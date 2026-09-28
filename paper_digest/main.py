"""일일 파이프라인: arXiv 수집 → 필터 → 중복 제거 → S2 보강 → Claude 요약 → 노션 기록 → 다이제스트."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import List

from .arxiv_client import fetch_recent_papers
from .config import ROOT, Settings, load_settings
from .filtering import filter_papers
from .models import ProcessedPaper
from .notion_api import NotionClient
from .fulltext import fetch_fulltext
from .semantic_scholar import enrich_papers
from .summarizer import make_summarizer

log = logging.getLogger("paper_digest")
KST = timezone(timedelta(hours=9))


def setup_logging() -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / f"run-{datetime.now(KST):%Y%m%d}.log", encoding="utf-8"),
    ]
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def require(settings: Settings, *names: str) -> None:
    missing = [n for n in names if not getattr(settings, n.lower())]
    if missing:
        sys.exit(f"환경변수 누락: {', '.join(missing)} (.env 또는 GitHub Secrets 확인)")


def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.lookback_hours:
        settings.lookback_hours = args.lookback_hours
    if args.limit:
        settings.max_papers_per_day = args.limit
    if settings.summarizer == "api":
        require(settings, "ANTHROPIC_API_KEY")
    if not args.dry_run:
        require(settings, "NOTION_TOKEN", "NOTION_DATABASE_ID")

    # 1) 수집 + 필터
    papers = fetch_recent_papers(settings.categories, settings.lookback_hours)
    log.info("최근 %d시간 %s 논문 %d편 수집", settings.lookback_hours, settings.categories, len(papers))
    candidates = filter_papers(papers, settings.filter_groups)
    log.info("주제 필터 통과: %d편", len(candidates))

    # 2) 노션 중복 제거 후 상한 적용
    notion = data_source_id = None
    if not args.dry_run:
        notion = NotionClient(settings.notion_token)
        data_source_id = notion.data_source_id(settings.notion_database_id)
        since = (datetime.now(timezone.utc) - timedelta(hours=settings.lookback_hours + 48)).date()
        existing = notion.existing_arxiv_urls(data_source_id, since)
        before = len(candidates)
        candidates = [p for p in candidates if p.abs_url not in existing]
        log.info("노션 중복 %d편 건너뜀", before - len(candidates))
    if len(candidates) > settings.max_papers_per_day:
        log.info("상한 %d편 적용 (나머지 %d편은 다음 실행에서 처리)",
                 settings.max_papers_per_day, len(candidates) - settings.max_papers_per_day)
        candidates = candidates[: settings.max_papers_per_day]

    # 3) 메타데이터 보강
    enrich_papers(candidates, settings.s2_api_key)

    # 4) 요약 + 노션 기록 — 논문 하나가 실패해도 계속 진행
    summarizer = make_summarizer(settings.summarizer, settings.claude_model,
                                 settings.interest_keywords, settings.anthropic_api_key)
    done: List[ProcessedPaper] = []
    failed = 0
    for i, paper in enumerate(candidates, 1):
        log.info("[%d/%d] %s — %s", i, len(candidates), paper.arxiv_id, paper.title[:80])
        try:
            if settings.summary_source == "fulltext":
                paper.fulltext = fetch_fulltext(paper.arxiv_id)
            summary = summarizer.summarize(paper)
            if args.dry_run:
                print(json.dumps({"arxiv": paper.abs_url, "citations": paper.citation_count,
                                  "max_author_citations": paper.max_author_citations,
                                  **summary.model_dump()}, ensure_ascii=False, indent=2))
                continue
            page = notion.create_paper_page(data_source_id, paper, summary,
                                            settings.icon_for(paper.primary_category))
            done.append(ProcessedPaper(paper, summary, page["id"], page["url"]))
            paper.fulltext = None  # 메모리 정리
            log.info("노션 페이지 생성: %s", page["url"])
        except Exception:
            failed += 1
            log.exception("논문 처리 실패: %s", paper.arxiv_id)

    # 5) 다이제스트
    if not args.dry_run:
        try:
            parent = settings.notion_digest_parent_page_id or notion.database_parent_page_id(
                settings.notion_database_id)
            if not parent:
                raise RuntimeError("다이제스트 부모 페이지를 찾을 수 없음 — NOTION_DIGEST_PARENT_PAGE_ID 설정 필요")
            digest = notion.create_digest_page(parent, datetime.now(KST).date(), done, failed)
            log.info("다이제스트 페이지 생성: %s", digest["url"])
        except Exception:
            log.exception("다이제스트 생성 실패")
            failed += 1

    log.info("완료: 성공 %d편, 실패 %d건", len(done), failed)
    # 전부 실패한 경우에만 비정상 종료 코드 (Actions에서 알림 받기 위함)
    return 1 if failed and not done and candidates else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="arXiv 논문 → Claude 요약 → 노션 다이제스트")
    parser.add_argument("--dry-run", action="store_true", help="노션에 쓰지 않고 요약 결과만 출력")
    parser.add_argument("--lookback-hours", type=int, help="config.yaml의 lookback_hours 덮어쓰기")
    parser.add_argument("--limit", type=int, help="config.yaml의 max_papers_per_day 덮어쓰기")
    args = parser.parse_args()
    setup_logging()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
