"""Playwright browser automation for scraping job listing pages."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright, TimeoutError as PwTimeout

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = PROJECT_ROOT / "data" / "screenshots"

CAPTCHA_INDICATORS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "challenge",
    "verify you are human",
    "are you a robot",
    "security check",
    "please verify",
    "unusual traffic",
    "bot detection",
]

# Board-specific wait selectors
BOARD_SELECTORS = {
    "indeed": {
        "wait": "div.jobsearch-JobComponent, div.jobsearch-ViewJobLayout, #jobDescriptionText",
        "timeout": 10000,
    },
    "glassdoor": {
        "wait": "div.JobDetails, div[data-test='jobListing'], #JDCol",
        "timeout": 10000,
    },
    "ziprecruiter": {
        "wait": "div.job_content, article.job_content, div.jobDescriptionSection",
        "timeout": 10000,
    },
    "greenhouse": {
        "wait": "#content, div.content, div#app_body",
        "timeout": 8000,
    },
    "lever": {
        "wait": "div.content, div.posting-page, div.section-wrapper",
        "timeout": 8000,
    },
}


class BrowserManager:
    def __init__(self, headless: bool = False, rate_limit: float = 4.0):
        self.headless = headless
        self.rate_limit = rate_limit
        self._last_nav = 0.0
        self._pw = None
        self._browser = None
        self._page: Page | None = None

    def _ensure_browser(self) -> Page:
        if self._page is not None:
            return self._page
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        self._page = context.new_page()
        return self._page

    def _rate_limit_wait(self) -> None:
        elapsed = time.time() - self._last_nav
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_nav = time.time()

    def detect_captcha(self, page: Page) -> bool:
        try:
            text = page.inner_text("body")[:3000].lower()
        except Exception:
            return False
        return any(ind in text for ind in CAPTCHA_INDICATORS)

    def screenshot(self, filename: str | None = None) -> str:
        page = self._ensure_browser()
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"captcha_{ts}.png"
        path = str(SCREENSHOTS_DIR / filename)
        page.screenshot(path=path)
        return path

    def scrape_page(self, url: str, board: str) -> dict:
        """Navigate to a job listing page and extract its text.

        Returns:
            {"text": str, "title": str, "url": str, "captcha": bool, "error": str | None}
        """
        page = self._ensure_browser()
        self._rate_limit_wait()

        board_key = board.lower()
        selector_info = BOARD_SELECTORS.get(board_key, {"wait": "body", "timeout": 10000})

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except PwTimeout:
            return {
                "text": "",
                "title": "",
                "url": url,
                "captcha": False,
                "error": f"Timeout loading {url}",
            }
        except Exception as e:
            return {
                "text": "",
                "title": "",
                "url": url,
                "captcha": False,
                "error": str(e),
            }

        # Wait for content
        try:
            page.wait_for_selector(selector_info["wait"], timeout=selector_info["timeout"])
        except PwTimeout:
            pass  # Continue anyway — page might still have useful content

        # Check for CAPTCHA
        if self.detect_captcha(page):
            ss_path = self.screenshot(f"captcha_{board_key}_{datetime.now().strftime('%H%M%S')}.png")
            print(
                f"[CAPTCHA] CAPTCHA detected on {board}. "
                f"Screenshot: {ss_path}. Please solve it manually."
            )
            return {
                "text": "",
                "title": page.title(),
                "url": str(page.url),
                "captcha": True,
                "error": f"CAPTCHA detected. Screenshot: {ss_path}",
            }

        # Extract text
        try:
            body_text = page.inner_text("body")
        except Exception:
            body_text = ""

        return {
            "text": body_text[:15000],  # Cap to avoid token overflow
            "title": page.title(),
            "url": str(page.url),
            "captcha": False,
            "error": None,
        }

    def close(self) -> None:
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
