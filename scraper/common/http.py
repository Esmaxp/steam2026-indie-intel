"""Rate-limited, retrying HTTP client for Steam endpoints."""

import asyncio
import json
import logging
import time

import aiohttp
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Steam2026IndieIntelligence/0.1 (+research tool; respects rate limits)"
)


class RetryableHTTPError(Exception):
    """429 / 5xx — worth retrying with backoff."""


class NonRetryableHTTPError(Exception):
    """Other 4xx — the server said no; retrying won't change that."""

    def __init__(self, status: int, url: str):
        self.status = status
        super().__init__(f"HTTP {status} for {url}")


class SteamClient:
    """One instance per rate-limit domain. Serializes requests with a minimum
    interval between them, retries transient failures with exponential backoff."""

    def __init__(self, session: aiohttp.ClientSession, min_interval: float = 1.0):
        self.session = session
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def _throttle(self) -> None:
        async with self._lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    @retry(
        retry=retry_if_exception_type(
            (RetryableHTTPError, aiohttp.ClientError, asyncio.TimeoutError)
        ),
        wait=wait_exponential_jitter(initial=2, max=60),
        stop=stop_after_attempt(6),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def get_text(self, url: str, params: dict | None = None) -> str:
        await self._throttle()
        async with self.session.get(url, params=params) as resp:
            if resp.status == 429 or resp.status >= 500:
                raise RetryableHTTPError(f"HTTP {resp.status} for {resp.url}")
            if resp.status >= 400:
                raise NonRetryableHTTPError(resp.status, str(resp.url))
            return await resp.text()

    async def get_json(self, url: str, params: dict | None = None) -> dict:
        text = await self.get_text(url, params=params)
        return json.loads(text)


def make_session(user_agent: str = USER_AGENT) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"},
        timeout=aiohttp.ClientTimeout(total=60),
    )
