"""Tool declarations and executor registry for Gemini function calling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from google.genai import types

from browser_automation import BrowserManager
from link_verifier import LinkVerifier

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Function Declarations ────────────────────────────────────────────────

SCRAPE_JOB_PAGE = types.FunctionDeclaration(
    name="scrape_job_page",
    description=(
        "Navigate to a job listing URL using a headless browser and extract "
        "the visible page text. Use this for Indeed, Glassdoor, ZipRecruiter, "
        "Greenhouse, and Lever pages. Do NOT use for LinkedIn URLs."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL of the job listing page",
            },
            "board_name": {
                "type": "string",
                "description": "The job board name (indeed, glassdoor, ziprecruiter, greenhouse, lever)",
            },
        },
        "required": ["url", "board_name"],
    },
)

VERIFY_LINK = types.FunctionDeclaration(
    name="verify_link",
    description=(
        "Check if a job listing URL is still live and active. "
        "Returns 'verified', 'dead', or 'redirected' with details."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The job listing URL to verify",
            },
        },
        "required": ["url"],
    },
)

NOTIFY_USER = types.FunctionDeclaration(
    name="notify_user",
    description="Print a notification message to the user (for CAPTCHA alerts, errors, important status updates).",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to display to the user",
            },
        },
        "required": ["message"],
    },
)

# All custom function declarations
CUSTOM_FUNCTION_DECLARATIONS = [SCRAPE_JOB_PAGE, VERIFY_LINK, NOTIFY_USER]

# Tool objects for Gemini
GOOGLE_SEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())
CUSTOM_FUNCTIONS_TOOL = types.Tool(function_declarations=CUSTOM_FUNCTION_DECLARATIONS)


class ToolExecutor:
    """Maps Gemini function call names to local implementations."""

    def __init__(self, browser: BrowserManager, verifier: LinkVerifier):
        self.browser = browser
        self.verifier = verifier
        self._registry: dict[str, Callable] = {
            "scrape_job_page": self._scrape_job_page,
            "verify_link": self._verify_link,
            "notify_user": self._notify_user,
        }

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a function call by name. Returns the result dict."""
        handler = self._registry.get(name)
        if handler is None:
            return {"error": f"Unknown function: {name}"}
        try:
            return handler(args)
        except Exception as e:
            return {"error": f"{name} failed: {e}"}

    def _scrape_job_page(self, args: dict) -> dict:
        result = self.browser.scrape_page(args["url"], args["board_name"])
        if result["error"]:
            return {"error": result["error"], "captcha": result["captcha"]}
        return {
            "page_text": result["text"],
            "page_title": result["title"],
            "final_url": result["url"],
        }

    def _verify_link(self, args: dict) -> dict:
        status, details = self.verifier.verify(args["url"])
        return {"status": status, "details": details}

    def _notify_user(self, args: dict) -> dict:
        msg = args["message"]
        print(f"[NOTIFICATION] {msg}")
        return {"status": "notified"}
