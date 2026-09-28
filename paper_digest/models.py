"""파이프라인 전반에서 쓰는 데이터 구조."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


@dataclass
class Paper:
    arxiv_id: str  # 버전 없는 ID (예: 2609.01234)
    title: str
    abstract: str
    authors: List[str]
    published: datetime
    categories: List[str]
    primary_category: str
    abs_url: str
    pdf_url: str
    filter_score: int = 0
    matched_terms: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)  # 필터에서 매칭된 주제 (예: "VLA Safety")

    # Semantic Scholar 보강 정보
    citation_count: Optional[int] = None
    influential_citation_count: Optional[int] = None
    max_author_citations: Optional[int] = None
    max_author_hindex: Optional[int] = None
    venue: Optional[str] = None

    # 요약 입력 (HTML 전문이 있으면 전문, 없으면 초록)
    fulltext: Optional[str] = None


class PaperSummary(BaseModel):
    """Claude 구조화 출력 스키마."""

    one_line_summary: str = Field(description="무엇을 했고 왜 중요한지 1~2문장 요약 (한국어)")
    problem: str = Field(description="문제 정의와 동기: 기존 접근의 한계와 이 논문이 풀려는 문제 (한국어, 3~4문장 문단)")
    key_contributions: List[str] = Field(description="핵심 기여 최대 3개. 각 항목 2~3문장으로 구체적으로 (한국어)")
    methodology: List[str] = Field(description="방법론 4~6개 불릿. 각 불릿은 구성요소·학습 방식·설계 선택을 1~2문장으로 (한국어)")
    results: List[str] = Field(description="주요 실험 결과 3~5개 불릿. 원문에 있는 수치·벤치마크·비교 대상 포함 (한국어)")
    limitations: List[str] = Field(description="한계점 2~4개 불릿 (한국어)")
    keywords: List[str] = Field(description="논문을 대표하는 영문 키워드 태그 3~5개")
    relevance_score: int = Field(description="관심 키워드 기준 관련도 1~5 정수")
    relevance_reason: str = Field(description="관련도 점수를 준 이유 1~2문장 (한국어)")


@dataclass
class ProcessedPaper:
    paper: Paper
    summary: PaperSummary
    page_id: str
    page_url: str
