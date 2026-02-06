"""Tests for ResilientHTTPClient."""

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from mercadolivre_upload.infrastructure.http import (
    NO_RETRY,
    SAFE_RETRY,
    UPLOAD_RETRY,
    ResilientHTTPClient,
    RetryPolicy,
    TokenBucketLimiter,
)


class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_retries == 3
        assert p.jitter is True
        assert 429 in p.retryable_statuses

    def test_no_retry(self):
        assert NO_RETRY.max_retries == 0

    def test_upload_retry(self):
        assert UPLOAD_RETRY.max_retries == 2
        assert UPLOAD_RETRY.base_delay == 2.0


class TestTokenBucketLimiter:
    def test_acquire_immediate(self):
        limiter = TokenBucketLimiter(rate=100, burst=10)
        start = time.monotonic()
        for _ in range(5):
            limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0

    def test_acquire_blocks(self):
        limiter = TokenBucketLimiter(rate=10, burst=1)
        limiter.acquire()  # consume the single token
        start = time.monotonic()
        limiter.acquire()  # should wait ~0.1s
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05


class TestResilientHTTPClient:
    def _mock_response(self, status_code=200, json_data=None, headers=None):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.headers = headers or {}
        resp.text = ""
        return resp

    def test_get_success(self):
        session = MagicMock()
        session.request.return_value = self._mock_response(200, {"ok": True})
        client = ResilientHTTPClient(session=session)

        resp = client.get("https://api.example.com/test")
        assert resp.status_code == 200
        session.request.assert_called_once()

    def test_post_success(self):
        session = MagicMock()
        session.request.return_value = self._mock_response(201)
        client = ResilientHTTPClient(session=session)

        resp = client.post("https://api.example.com/items", json={"title": "x"})
        assert resp.status_code == 201

    @patch("mercadolivre_upload.infrastructure.http.time.sleep")
    def test_retry_on_429(self, mock_sleep):
        session = MagicMock()
        r429 = self._mock_response(429, headers={"Retry-After": "1"})
        r200 = self._mock_response(200)
        session.request.side_effect = [r429, r200]

        client = ResilientHTTPClient(session=session)
        resp = client.get("https://api.example.com/test")

        assert resp.status_code == 200
        assert session.request.call_count == 2
        mock_sleep.assert_called_once()

    @patch("mercadolivre_upload.infrastructure.http.time.sleep")
    def test_retry_on_500(self, mock_sleep):
        session = MagicMock()
        r500 = self._mock_response(500)
        r200 = self._mock_response(200)
        session.request.side_effect = [r500, r500, r200]

        client = ResilientHTTPClient(session=session)
        resp = client.get("https://api.example.com/test")

        assert resp.status_code == 200
        assert session.request.call_count == 3

    @patch("mercadolivre_upload.infrastructure.http.time.sleep")
    def test_exhausted_retries_returns_last_response(self, mock_sleep):
        session = MagicMock()
        r429 = self._mock_response(429)
        session.request.return_value = r429

        policy = RetryPolicy(max_retries=2, jitter=False)
        client = ResilientHTTPClient(session=session, default_policy=policy)
        resp = client.get("https://api.example.com/test")

        assert resp.status_code == 429
        assert session.request.call_count == 3  # 1 + 2 retries

    @patch("mercadolivre_upload.infrastructure.http.time.sleep")
    def test_respects_retry_after_header(self, mock_sleep):
        session = MagicMock()
        r429 = self._mock_response(429, headers={"Retry-After": "5"})
        r200 = self._mock_response(200)
        session.request.side_effect = [r429, r200]

        client = ResilientHTTPClient(session=session)
        client.get("https://api.example.com/test")

        delay_used = mock_sleep.call_args[0][0]
        assert delay_used == 5.0

    def test_no_retry_policy(self):
        session = MagicMock()
        r500 = self._mock_response(500)
        session.request.return_value = r500

        client = ResilientHTTPClient(session=session)
        resp = client.get("https://api.example.com/test", policy=NO_RETRY)

        assert resp.status_code == 500
        assert session.request.call_count == 1

    @patch("mercadolivre_upload.infrastructure.http.time.sleep")
    def test_connection_error_retry(self, mock_sleep):
        session = MagicMock()
        session.request.side_effect = [
            requests.ConnectionError("refused"),
            self._mock_response(200),
        ]

        client = ResilientHTTPClient(session=session)
        resp = client.get("https://api.example.com/test")
        assert resp.status_code == 200

    @patch("mercadolivre_upload.infrastructure.http.time.sleep")
    def test_timeout_error_retry(self, mock_sleep):
        session = MagicMock()
        session.request.side_effect = [
            requests.Timeout("timed out"),
            self._mock_response(200),
        ]

        client = ResilientHTTPClient(session=session)
        resp = client.get("https://api.example.com/test")
        assert resp.status_code == 200

    def test_non_retryable_status_returns_immediately(self):
        session = MagicMock()
        r400 = self._mock_response(400)
        session.request.return_value = r400

        client = ResilientHTTPClient(session=session)
        resp = client.get("https://api.example.com/test")

        assert resp.status_code == 400
        assert session.request.call_count == 1

    def test_rate_limiter_used(self):
        limiter = MagicMock(spec=TokenBucketLimiter)
        session = MagicMock()
        session.request.return_value = self._mock_response(200)

        client = ResilientHTTPClient(session=session, limiter=limiter)
        client.get("https://api.example.com/test")

        limiter.acquire.assert_called_once()

    def test_put_method(self):
        session = MagicMock()
        session.request.return_value = self._mock_response(200)
        client = ResilientHTTPClient(session=session)

        resp = client.put("https://api.example.com/items/1", json={"title": "y"})
        assert resp.status_code == 200
        call_args = session.request.call_args
        assert call_args[0][0] == "PUT"
