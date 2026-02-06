"""Resilient HTTP client with retry, backoff, jitter and rate limiting.

Wraps requests.Session with:
- Exponential backoff + jitter on retryable status codes (429, 500, 502, 503, 504)
- Respect for Retry-After header
- Configurable per-endpoint policies
- Token-bucket rate limiting
- Structured logging of retries and failures

All configuration is read from infrastructure.config.Settings or passed explicitly.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from threading import Lock

import requests

logger = logging.getLogger(__name__)

# Default retryable HTTP status codes
DEFAULT_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Per-request retry policy."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_factor: float = 2.0
    jitter: bool = True
    retryable_statuses: frozenset[int] = DEFAULT_RETRYABLE_STATUSES
    idempotent: bool = True


# Shared policies — importable by other modules
SAFE_RETRY = RetryPolicy()
NO_RETRY = RetryPolicy(max_retries=0)
UPLOAD_RETRY = RetryPolicy(max_retries=2, base_delay=2.0, max_delay=30.0)
NON_IDEMPOTENT = RetryPolicy(max_retries=0, idempotent=False)


class TokenBucketLimiter:
    """Simple thread-safe token-bucket rate limiter."""

    def __init__(self, rate: float = 2.0, burst: int = 5):
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(0.05)


class ResilientHTTPClient:
    """HTTP client with retry/backoff/rate-limiting built in."""

    def __init__(
        self,
        *,
        timeout: int = 30,
        default_policy: RetryPolicy | None = None,
        limiter: TokenBucketLimiter | None = None,
        session: requests.Session | None = None,
    ):
        self.timeout = timeout
        self.default_policy = default_policy or SAFE_RETRY
        self.limiter = limiter
        self.session = session or requests.Session()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        policy: RetryPolicy | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        return self._request(
            "GET", url, headers=headers, params=params, policy=policy, timeout=timeout
        )

    def post(
        self,
        url: str,
        *,
        headers: dict | None = None,
        json: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        policy: RetryPolicy | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            url,
            headers=headers,
            json=json,
            data=data,
            files=files,
            policy=policy,
            timeout=timeout,
        )

    def put(
        self,
        url: str,
        *,
        headers: dict | None = None,
        json: dict | None = None,
        policy: RetryPolicy | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        return self._request(
            "PUT", url, headers=headers, json=json, policy=policy, timeout=timeout
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        policy: RetryPolicy | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        policy = policy or self.default_policy
        effective_timeout = timeout or self.timeout
        last_exc: Exception | None = None

        for attempt in range(policy.max_retries + 1):
            if self.limiter:
                self.limiter.acquire()

            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                    timeout=effective_timeout,
                )

                if resp.status_code not in policy.retryable_statuses:
                    return resp

                # Retryable status — decide whether to retry
                if attempt >= policy.max_retries:
                    return resp

                delay = self._compute_delay(resp, attempt, policy)
                logger.warning(
                    "%s %s returned %d, retrying in %.1fs (%d/%d)",
                    method,
                    url,
                    resp.status_code,
                    delay,
                    attempt + 1,
                    policy.max_retries,
                )
                time.sleep(delay)

            except requests.ConnectionError as exc:
                last_exc = exc
                if attempt >= policy.max_retries:
                    raise
                delay = self._compute_delay(None, attempt, policy)
                logger.warning(
                    "%s %s connection error, retrying in %.1fs (%d/%d): %s",
                    method,
                    url,
                    delay,
                    attempt + 1,
                    policy.max_retries,
                    exc,
                )
                time.sleep(delay)

            except requests.Timeout as exc:
                last_exc = exc
                if attempt >= policy.max_retries:
                    raise
                delay = self._compute_delay(None, attempt, policy)
                logger.warning(
                    "%s %s timeout, retrying in %.1fs (%d/%d)",
                    method,
                    url,
                    delay,
                    attempt + 1,
                    policy.max_retries,
                )
                time.sleep(delay)

        # Should not reach here, but just in case
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Exhausted retries for {method} {url}")

    @staticmethod
    def _compute_delay(
        response: requests.Response | None,
        attempt: int,
        policy: RetryPolicy,
    ) -> float:
        """Compute sleep delay respecting Retry-After if present."""
        # Check Retry-After header
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return min(float(retry_after), policy.max_delay)
                except ValueError:
                    pass

        delay = policy.base_delay * (policy.backoff_factor ** attempt)
        delay = min(delay, policy.max_delay)

        if policy.jitter:
            delay *= 0.5 + random.random()  # noqa: S311

        return delay
