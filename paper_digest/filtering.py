"""제목+초록에 대한 정규식 기반 주제 필터."""
from __future__ import annotations

import re
from typing import Dict, List

from .models import Paper


def filter_papers(papers: List[Paper], groups: Dict[str, List[str]]) -> List[Paper]:
    """모든 그룹에서 최소 1개 패턴이 매칭되는 논문만 남기고, 매칭 수 내림차순으로 정렬."""
    compiled = {name: [re.compile(p, re.IGNORECASE) for p in pats] for name, pats in groups.items()}
    selected = []
    for paper in papers:
        text = f"{paper.title}\n{paper.abstract}"
        matched: List[str] = []
        score = 0
        ok = True
        for pats in compiled.values():
            hits = [m.group(0).lower() for p in pats for m in [p.search(text)] if m]
            if not hits:
                ok = False
                break
            matched.extend(hits)
            # 제목 매칭은 가중치 2배
            score += len(hits) + sum(1 for p in pats if p.search(paper.title))
        if ok:
            paper.filter_score = score
            paper.matched_terms = sorted(set(matched))
            selected.append(paper)
    selected.sort(key=lambda p: (p.filter_score, p.published), reverse=True)
    return selected
