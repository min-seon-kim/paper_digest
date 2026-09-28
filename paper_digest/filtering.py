"""제목+초록에 대한 정규식 기반 주제 필터.

주제(topic)끼리는 OR, 한 주제 안의 그룹끼리는 AND.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .models import Paper

Topics = Dict[str, Dict[str, List[str]]]


def _match_topic(paper: Paper, groups: Dict[str, List[re.Pattern]]):
    """주제의 모든 그룹이 매칭되면 (점수, 매칭 단어) 반환, 아니면 None."""
    text = f"{paper.title}\n{paper.abstract}"
    matched: List[str] = []
    score = 0
    for pats in groups.values():
        hits = [m.group(0).lower() for p in pats for m in [p.search(text)] if m]
        if not hits:
            return None
        matched.extend(hits)
        # 제목 매칭은 가중치 2배
        score += len(hits) + sum(1 for p in pats if p.search(paper.title))
    return score, matched


def filter_papers(papers: List[Paper], topics: Topics) -> List[Paper]:
    """하나 이상의 주제를 만족하는 논문만 남기고, 점수 내림차순으로 정렬."""
    compiled = {
        topic: {g: [re.compile(p, re.IGNORECASE) for p in pats] for g, pats in groups.items()}
        for topic, groups in topics.items()
    }
    selected = []
    for paper in papers:
        best = 0
        matched: List[str] = []
        paper.topics = []
        for topic, groups in compiled.items():
            result = _match_topic(paper, groups)
            if result is None:
                continue
            paper.topics.append(topic)
            best = max(best, result[0])
            matched.extend(result[1])
        if paper.topics:
            paper.filter_score = best
            paper.matched_terms = sorted(set(matched))
            selected.append(paper)
    selected.sort(key=lambda p: (p.filter_score, p.published), reverse=True)
    return selected
