"""Polite HTTP: per-host spacing, bounded retries with jittered backoff, fixed User-Agent.

The transport is injectable so tests run offline. `UrllibTransport` honours HTTPS_PROXY and keeps
cookies per session (some `www.nseindia.com` endpoints may need a warm-up page visit; from a cloud
container the API answered without one [A1], so warm-up is optional).
"""

from __future__ import annotations

import http.cookiejar
import random
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) financials-research/0.1 (personal, non-commercial)"
RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    def __init__(self, url: str, status: int | None, message: str) -> None:
        super().__init__(f"{url}: {status} {message}")
        self.url, self.status = url, status


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: float) -> Response: ...


class UrllibTransport:
    def __init__(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def get(self, url: str, headers: dict[str, str], timeout: float) -> Response:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return Response(r.status, r.read(), dict(r.headers.items()))
        except urllib.error.HTTPError as e:
            return Response(e.code, e.read() if e.fp else b"", dict(e.headers.items()) if e.headers else {})


class PoliteFetcher:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval: float = 1.0,
        max_attempts: int = 4,
        base_backoff: float = 2.0,
        timeout: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        warmup: dict[str, str] | None = None,
    ) -> None:
        self.transport = transport or UrllibTransport()
        self.user_agent, self.min_interval, self.max_attempts = user_agent, min_interval, max_attempts
        self.base_backoff, self.timeout, self.sleep, self.clock = base_backoff, timeout, sleep, clock
        self.rng = rng or random.Random()
        self.warmup = warmup or {}  # host -> page to visit once per session before API calls
        self._last: dict[str, float] = {}
        self._warmed: set[str] = set()
        self.requests: list[str] = []
        # Thread safety: one lock per host serialises that host's requests, so the >= min_interval spacing holds with
        # any number of worker threads; different hosts proceed in parallel (the only gain parallel workers give).
        self._host_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _host_lock(self, host: str) -> threading.Lock:
        with self._locks_guard:
            return self._host_locks.setdefault(host, threading.Lock())

    def _space(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.min_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last[host] = self.clock()

    def _raw(self, url: str, accept: str) -> Response:
        host = urlsplit(url).netloc
        headers = {"User-Agent": self.user_agent, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"}
        with self._host_lock(host):  # spacing + request under the host lock: never two in flight per host
            self._space(host)
            self.requests.append(url)
            r = self.transport.get(url, headers, self.timeout)
            self._last[host] = self.clock()
            return r

    def get(self, url: str, *, accept: str = "*/*", allow_404: bool = False) -> bytes | None:
        host = urlsplit(url).netloc
        with self._locks_guard:
            warm = host in self.warmup and host not in self._warmed
            if warm:
                self._warmed.add(host)
        if warm:
            self._raw(self.warmup[host], "text/html")
        last_status: int | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = self._raw(url, accept)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_status, message = None, str(exc)
            else:
                if r.status == 200:
                    return r.body
                if r.status == 404 and allow_404:
                    return None
                last_status, message = r.status, "HTTP error"
                if r.status not in RETRY_STATUSES:
                    break
            if attempt < self.max_attempts:
                delay = self.base_backoff * 2 ** (attempt - 1)
                self.sleep(delay * (0.5 + self.rng.random()))
        raise FetchError(url, last_status, message)
