"""논문을 한국어 구조화 요약(JSON)으로 변환.

두 가지 백엔드:
- claude_code (기본): Claude Code CLI(`claude -p`)를 헤드리스로 호출. Claude 구독(Pro/Max)
  로그인 또는 CLAUDE_CODE_OAUTH_TOKEN으로 인증하므로 별도 API 키가 필요 없다.
- api: Anthropic API를 SDK로 직접 호출. ANTHROPIC_API_KEY 필요.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from typing import List, Optional

from pydantic import ValidationError

from .models import Paper, PaperSummary

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 AI·로보틱스 연구 논문을 정리해 주는 연구 보조입니다. 주어진 arXiv 논문을 읽고, 논문을 직접 읽을 시간이 없는 연구자가 이 요약만으로 무엇을 왜 어떻게 했고 결과가 어땠는지 파악할 수 있도록 한국어로 충실하게 정리하세요.

각 필드 작성 기준:
- one_line_summary: 무엇을 했고 왜 중요한지 1~2문장.
- problem: 기존 접근의 한계와 이 논문이 풀려는 문제를 3~4문장 문단으로.
- key_contributions: 핵심 기여 최대 3개. 각 항목은 "무엇을 제안/발견했는지 + 그것이 왜 새로운지"를 2~3문장으로.
- methodology: 4~6개 불릿. 모델 구조, 핵심 알고리즘, 학습·추론 방식, 중요한 설계 선택을 구체적으로 (각 1~2문장).
- results: 3~5개 불릿. 평가 환경·벤치마크, 비교 대상(baseline), 핵심 수치를 원문 그대로 인용. 원문에 없는 수치는 절대 만들지 마세요.
- limitations: 2~4개 불릿. 저자가 밝힌 한계를 우선 쓰고, 합리적으로 추론한 한계는 "(추정)"이라고 표시.
- keywords: 논문을 대표하는 영문 키워드 태그 3~5개 (예: "VLA", "jailbreak", "safety filter").
- relevance_score: 아래 '관심 키워드'와의 관련도를 1~5 정수로 채점.
  5=관심 주제를 정면으로 다룸, 4=핵심 부분이 겹침, 3=부분적으로 관련, 2=주변적 관련, 1=거의 무관.
- relevance_reason: 그 점수를 준 이유 1~2문장.

모델명·데이터셋명·지표 같은 고유명사는 원문 표기를 유지하세요."""

# 구조화 출력 JSON Schema (Claude Code CLI용)
SUMMARY_SCHEMA = {**PaperSummary.model_json_schema(), "additionalProperties": False}


def build_user_prompt(paper: Paper, interests: str) -> str:
    source = "본문 전체" if paper.fulltext else "초록 (HTML 전문이 없어 초록만 제공됨 — 결과 수치는 초록에 있는 것만 쓰세요)"
    body = paper.fulltext or paper.abstract
    return (
        f"## 관심 키워드\n{interests}\n\n"
        f"## 논문 정보\n제목: {paper.title}\n"
        f"저자: {', '.join(paper.authors[:10])}\n"
        f"카테고리: {', '.join(paper.categories)}\n\n"
        f"## 초록\n{paper.abstract}\n\n"
        f"## 제공된 입력: {source}\n{body if paper.fulltext else ''}"
    )


def _postprocess(summary: PaperSummary) -> PaperSummary:
    summary.key_contributions = summary.key_contributions[:3]
    summary.keywords = summary.keywords[:5]
    summary.relevance_score = max(1, min(5, summary.relevance_score))
    return summary


def find_claude_cli() -> Optional[str]:
    """PATH의 claude → CLAUDE_CLI 환경변수 → VS Code 확장에 번들된 바이너리 순으로 탐색."""
    if os.getenv("CLAUDE_CLI"):
        return os.environ["CLAUDE_CLI"]
    found = shutil.which("claude")
    if found:
        return found
    bundled = sorted(glob.glob(os.path.expanduser(
        "~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude")))
    return bundled[-1] if bundled else None


class ClaudeCodeSummarizer:
    """`claude -p --json-schema`로 구독 인증을 사용해 요약."""

    def __init__(self, model: str, interest_keywords: List[str], timeout: int = 600, max_retries: int = 3):
        self.cli = find_claude_cli()
        if not self.cli:
            raise RuntimeError("Claude Code CLI를 찾을 수 없습니다. `npm i -g @anthropic-ai/claude-code` 후 "
                               "`claude` 로그인, 또는 CLAUDE_CLI 환경변수로 경로 지정")
        self.model = model
        self.interests = "\n".join(f"- {k}" for k in interest_keywords)
        self.timeout = timeout
        self.max_retries = max_retries
        # 프로젝트 설정·CLAUDE.md 등의 영향을 받지 않도록 빈 임시 폴더에서 실행
        self.workdir = tempfile.mkdtemp(prefix="paper-digest-")
        # .env의 ANTHROPIC_API_KEY(자리표시자 포함)가 구독 인증보다 우선되지 않도록 제거
        self.env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    def _run_once(self, prompt: str) -> PaperSummary:
        cmd = [
            self.cli, "-p",
            "--model", self.model,
            "--append-system-prompt", SYSTEM_PROMPT,
            "--tools", "",
            "--no-session-persistence",
            "--output-format", "json",
            "--json-schema", json.dumps(SUMMARY_SCHEMA, ensure_ascii=False),
        ]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              timeout=self.timeout, cwd=self.workdir, env=self.env)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"CLI 출력 파싱 실패 (exit {proc.returncode}): "
                               f"{(proc.stderr or proc.stdout)[:500]}")
        if data.get("is_error") or data.get("subtype") != "success":
            raise RuntimeError(f"Claude Code 오류: {data.get('api_error_status')} {str(data.get('result'))[:300]}")
        structured = data.get("structured_output")
        if structured is None:
            raise RuntimeError("structured_output 없음")
        return PaperSummary.model_validate(structured)

    def summarize(self, paper: Paper) -> PaperSummary:
        prompt = build_user_prompt(paper, self.interests)
        last: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                summary = _postprocess(self._run_once(prompt))
                log.info("요약 완료: %s (관련도 %d, 입력=%s)", paper.arxiv_id, summary.relevance_score,
                         "전문" if paper.fulltext else "초록")
                return summary
            except (RuntimeError, ValidationError, subprocess.TimeoutExpired) as exc:
                last = exc
                # 사용량 한도(429)·일시적 오류 대비 백오프
                delay = 30 * (2 ** attempt)
                log.warning("요약 실패 %s (%d/%d): %s → %d초 후 재시도", paper.arxiv_id,
                            attempt + 1, self.max_retries, exc, delay)
                if attempt < self.max_retries - 1:
                    time.sleep(delay)
        raise RuntimeError(f"요약 최종 실패: {last}")


class ApiSummarizer:
    """Anthropic SDK로 직접 호출 (ANTHROPIC_API_KEY 필요)."""

    def __init__(self, api_key: str, model: str, interest_keywords: List[str]):
        import anthropic

        # SDK 자체 재시도(429/5xx/연결 오류, 지수 백오프)를 기본 2회 → 5회로 늘림
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=5)
        self.model = model
        self.interests = "\n".join(f"- {k}" for k in interest_keywords)

    def summarize(self, paper: Paper) -> PaperSummary:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(paper, self.interests)}],
            output_config={"format": {"type": "json_schema", "schema": SUMMARY_SCHEMA}},
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude가 요약을 거절함: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("응답이 max_tokens에서 잘림")
        raw = next(b.text for b in response.content if b.type == "text")
        summary = _postprocess(PaperSummary.model_validate_json(raw))
        log.info("요약 완료: %s (관련도 %d, in=%d out=%d tokens)", paper.arxiv_id,
                 summary.relevance_score, response.usage.input_tokens, response.usage.output_tokens)
        return summary


def make_summarizer(backend: str, model: str, interest_keywords: List[str], api_key: Optional[str]):
    if backend == "api":
        if not api_key:
            raise SystemExit("summarizer: api 모드에는 ANTHROPIC_API_KEY가 필요합니다.")
        return ApiSummarizer(api_key, model, interest_keywords)
    return ClaudeCodeSummarizer(model, interest_keywords)
