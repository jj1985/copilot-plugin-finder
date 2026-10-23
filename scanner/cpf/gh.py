"""GitHub REST + GraphQL client with header-driven rate limiting and retries.

Observed limits (2026-10-22, authenticated): code search 10 req/min, search 30 req/min,
core 5000/h, GraphQL 5000 points/h with a ~10 s execution timeout that returns HTTP 502.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("cpf.gh")

API = "https://api.github.com"
CODE_SEARCH_MIN_INTERVAL = 6.2  # seconds; 10/min with headroom


class GitHubError(Exception):
    pass


class GraphQLTimeout(GitHubError):
    """502/504 or a 'timeout' error from GraphQL: the batch was too big."""


class NotFound(GitHubError):
    pass


@dataclass
class Counters:
    code_search: int = 0
    search: int = 0
    core: int = 0
    graphql: int = 0
    graphql_points: int = 0
    retries: int = 0
    sleeps: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class _Bucket:
    remaining: int | None = None
    reset_at: float | None = None
    last_call: float = 0.0


class GitHub:
    def __init__(self, token: str, user_agent: str = "cpf-scanner/0.1 (+https://github.com/jj1985)") -> None:
        self._client = httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": user_agent,
            },
            timeout=httpx.Timeout(60.0, connect=20.0),
        )
        self.counters = Counters()
        self._buckets: dict[str, _Bucket] = {k: _Bucket() for k in ("code_search", "search", "core", "graphql")}

    # ---------- low level ----------

    def _sleep(self, seconds: float, why: str) -> None:
        seconds = max(0.0, seconds)
        if seconds >= 1:
            log.info("sleeping %.1fs (%s)", seconds, why)
        self.counters.sleeps += seconds
        time.sleep(seconds)

    def _pre(self, bucket: str) -> None:
        b = self._buckets[bucket]
        nowt = time.time()
        if bucket == "code_search":
            wait = b.last_call + CODE_SEARCH_MIN_INTERVAL - nowt
            if wait > 0:
                self._sleep(wait, "code search pacing")
        if b.remaining is not None and b.remaining <= 0 and b.reset_at and b.reset_at > time.time():
            self._sleep(b.reset_at - time.time() + 1, f"{bucket} exhausted")

    def _post(self, bucket: str, resp: httpx.Response) -> None:
        b = self._buckets[bucket]
        b.last_call = time.time()
        try:
            if "x-ratelimit-remaining" in resp.headers:
                b.remaining = int(resp.headers["x-ratelimit-remaining"])
            if "x-ratelimit-reset" in resp.headers:
                b.reset_at = float(resp.headers["x-ratelimit-reset"])
        except ValueError:
            pass

    def _request(self, method: str, url: str, bucket: str, *, params: dict | None = None, json: Any = None,
                 headers: dict | None = None, max_attempts: int = 7) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            self._pre(bucket)
            try:
                resp = self._client.request(method, url, params=params, json=json, headers=headers)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt >= max_attempts:
                    raise GitHubError(f"transport failure after {attempt} attempts: {exc}") from exc
                self.counters.retries += 1
                self._sleep(min(60, 2 ** attempt) + random.random(), f"transport error {exc.__class__.__name__}")
                continue
            self._post(bucket, resp)
            setattr(self.counters, bucket, getattr(self.counters, bucket) + 1)
            if resp.status_code < 400:
                return resp
            if resp.status_code in (403, 429):
                if attempt >= max_attempts:
                    raise GitHubError(f"rate limited after {attempt} attempts: {resp.text[:200]}")
                self.counters.retries += 1
                ra = resp.headers.get("retry-after")
                if ra and ra.isdigit():
                    self._sleep(int(ra) + 1, "retry-after")
                elif resp.headers.get("x-ratelimit-remaining") == "0" and resp.headers.get("x-ratelimit-reset"):
                    self._sleep(float(resp.headers["x-ratelimit-reset"]) - time.time() + 2, "primary limit reset")
                else:
                    self._sleep(min(120, 10 * 2 ** (attempt - 1)) + random.random() * 3, "secondary limit backoff")
                continue
            if resp.status_code == 404:
                raise NotFound(url)
            if resp.status_code == 422:
                raise GitHubError(f"422 {resp.text[:300]}")
            if resp.status_code in (502, 503, 504):
                if bucket == "graphql":
                    raise GraphQLTimeout(f"{resp.status_code} from GraphQL")
                if attempt >= max_attempts:
                    raise GitHubError(f"{resp.status_code} after {attempt} attempts")
                self.counters.retries += 1
                self._sleep(min(60, 3 * 2 ** (attempt - 1)) + random.random(), f"{resp.status_code}")
                continue
            raise GitHubError(f"{resp.status_code} {method} {url}: {resp.text[:300]}")

    # ---------- REST ----------

    def rate_limit(self) -> dict[str, Any]:
        return self._request("GET", "/rate_limit", "core").json()["resources"]

    def search_code(self, q: str, page: int = 1, per_page: int = 100, *, sort: str | None = None,
                    text_match: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {"q": q, "page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
            params["order"] = "desc"
        headers = {"Accept": "application/vnd.github.text-match+json"} if text_match else None
        return self._json(self._request("GET", "/search/code", "code_search", params=params, headers=headers))

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise GitHubError(f"non-JSON response from {resp.request.url.path} ({resp.status_code})") from exc

    def search_repos(self, q: str, page: int = 1, per_page: int = 100, sort: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"q": q, "page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        return self._request("GET", "/search/repositories", "search", params=params).json()

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, "core", params=params or None).json()

    # ---------- GraphQL ----------

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return `data`. Raises GraphQLTimeout for 502/504 or timeout-shaped errors."""
        attempt = 0
        while True:
            attempt += 1
            resp = self._request("POST", "/graphql", "graphql", json={"query": query, "variables": variables or {}})
            try:
                body = resp.json()
            except ValueError:
                # Non-JSON body with a 2xx status happens on gateway hiccups; treat like a timeout so the batch shrinks.
                raise GraphQLTimeout(f"non-JSON GraphQL response ({resp.status_code}, {len(resp.content)} bytes)")
            if not isinstance(body, dict):
                raise GraphQLTimeout("unexpected GraphQL body shape")
            errors = body.get("errors") or []
            data = body.get("data") or {}
            rl = data.get("rateLimit") if isinstance(data, dict) else None
            if rl and isinstance(rl.get("cost"), int):
                self.counters.graphql_points += rl["cost"]
                self._buckets["graphql"].remaining = rl.get("remaining")
            if errors:
                types = {e.get("type") for e in errors}
                msgs = " | ".join(str(e.get("message", ""))[:160] for e in errors[:3])
                if "RATE_LIMITED" in types:
                    if attempt >= 5:
                        raise GitHubError(f"GraphQL rate limited: {msgs}")
                    self._sleep(60 * attempt, "GraphQL RATE_LIMITED")
                    continue
                if any("timeout" in m.lower() or "something went wrong" in m.lower() for m in [msgs]):
                    raise GraphQLTimeout(msgs)
                # Partial data with per-node errors (e.g. NOT_FOUND) is normal for nodes(ids:); return data.
                if not data:
                    raise GitHubError(f"GraphQL errors: {msgs}")
                log.debug("GraphQL partial errors: %s", msgs)
            return data

    def close(self) -> None:
        self._client.close()
