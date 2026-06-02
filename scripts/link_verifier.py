"""URL verification for job listings using httpx."""

from __future__ import annotations

import time

import httpx

DEAD_INDICATORS = [
    "not found",
    "no longer available",
    "has been filled",
    "position closed",
    "position has been filled",
    "job has expired",
    "this job is no longer",
    "sorry, this position",
    "page not found",
    "404",
    "this role has been filled",
    "no longer accepting applications",
    "this posting has expired",
    "job no longer exists",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class LinkVerifier:
    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self._last_request = 0.0
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": USER_AGENT},
        )

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()

    def verify(self, url: str) -> tuple[str, str | None]:
        """Check if a job URL is live.

        Returns (status, details) where status is one of:
        "verified", "dead", "redirected".
        """
        self._wait()
        try:
            resp = self.client.get(url)
        except httpx.HTTPError as e:
            return "dead", f"HTTP error: {e}"

        if resp.status_code in (404, 410, 403):
            return "dead", f"HTTP {resp.status_code}"

        if resp.status_code >= 400:
            return "dead", f"HTTP {resp.status_code}"

        # Check if redirected to a generic careers page (not the specific job)
        final_url = str(resp.url)
        if final_url != url:
            # Redirected — check if it landed on a generic page
            url_lower = final_url.lower()
            if any(
                pattern in url_lower
                for pattern in ["/careers", "/jobs?", "/search?", "/openings"]
            ):
                # Redirected to a generic careers listing, not the specific job
                if url.lower().rstrip("/") != final_url.lower().rstrip("/"):
                    return "redirected", f"Redirected to generic page: {final_url}"

        # Check page content for dead indicators
        text = resp.text[:5000].lower()
        title_match = ""
        if "<title>" in text:
            start = text.index("<title>") + 7
            end = text.index("</title>", start) if "</title>" in text[start:] else start + 200
            title_match = text[start:end]

        check_text = title_match + " " + text[:3000]
        for indicator in DEAD_INDICATORS:
            if indicator in check_text:
                return "dead", f"Page contains: '{indicator}'"

        return "verified", None

    def batch_verify(self, urls: list[str]) -> dict[str, tuple[str, str | None]]:
        """Verify multiple URLs. Returns {url: (status, details)}."""
        results = {}
        for url in urls:
            results[url] = self.verify(url)
        return results

    def close(self) -> None:
        self.client.close()
