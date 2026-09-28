"""rate limit(429)·일시적 서버 오류(5xx)에 대해 지수 백오프로 재시도하는 HTTP 헬퍼."""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_retries: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    timeout: float = 30.0,
    **kwargs: Any,
) -> requests.Response:
    """429/5xx/네트워크 오류 시 재시도. Retry-After 헤더가 있으면 그 값을 우선 따른다.

    재시도로도 실패하면 마지막 응답에 대해 raise_for_status()로 예외를 던진다.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = session.request(method, url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            resp = None
        if resp is not None and resp.status_code not in RETRY_STATUS:
            resp.raise_for_status()
            return resp
        if attempt == max_retries:
            break

        delay = min(max_delay, base_delay * (2**attempt)) + random.uniform(0, 1)
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
            reason = f"HTTP {resp.status_code}"
        else:
            reason = repr(last_exc)
        log.warning("%s %s 실패 (%s) → %.1f초 후 재시도 (%d/%d)",
                    method, url.split("?")[0], reason, delay, attempt + 1, max_retries)
        time.sleep(delay)

    if resp is not None:
        resp.raise_for_status()
    raise last_exc  # type: ignore[misc]
