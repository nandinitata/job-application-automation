#!/usr/bin/env python3
"""Gemini 2.5 Pro powered job search agent.

Replaces the Claude Code search agent with a standalone script that uses
Gemini's native Google Search grounding for better job discovery.

Usage:
    python3 scripts/gemini_search_agent.py
    python3 scripts/gemini_search_agent.py --boards linkedin,indeed --max-per-board 20
    python3 scripts/gemini_search_agent.py --dry-run --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add scripts dir to path so local imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from google import genai
from google.genai import types

from browser_automation import BrowserManager
from gemini_tools import (
    GOOGLE_SEARCH_TOOL,
    ToolExecutor,
)
from job_schema import JobListing, JobsFoundFile, SearchMetadata
from link_verifier import LinkVerifier

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-2.5-flash-lite"
RETRY_DELAY_SECONDS = [5, 15, 30]

# ── Config loading ───────────────────────────────────────────────────────


def load_config() -> tuple[dict, dict, dict]:
    with open(CONFIG_DIR / "user_profile.json") as f:
        profile = json.load(f)
    with open(CONFIG_DIR / "job_boards.json") as f:
        boards = json.load(f)
    with open(CONFIG_DIR / "search_queries.json") as f:
        queries = json.load(f)
    return profile, boards, queries


def load_existing_jobs() -> list[dict]:
    path = DATA_DIR / "jobs_found.json"
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return data.get("jobs", [])


def _safe_lower(val: str | None) -> str:
    return (val or "").lower().strip()


def _dedup_key(job: dict) -> str:
    return f"{_safe_lower(job.get('title'))}|{_safe_lower(job.get('company'))}|{_safe_lower(job.get('location'))}"


def build_existing_index(jobs: list[dict]) -> set[str]:
    """Build a set of dedup keys from existing jobs."""
    keys = set()
    for j in jobs:
        if j.get("url"):
            keys.add(j["url"])
        keys.add(_dedup_key(j))
    return keys


# ── System prompt ────────────────────────────────────────────────────────


def build_system_prompt(
    profile: dict, boards: dict, queries: dict, existing_count: int
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    target_roles = profile["preferences"]["target_roles"]
    roles_str = ", ".join(target_roles)

    enabled_boards = [b["name"] for b in boards["boards"] if b.get("enabled", True)]
    boards_str = ", ".join(enabled_boards)

    return (
        f"You are a job search agent. Today is {today}. "
        f"Find entry-level/new-grad ML, AI, Data Science, NLP jobs in the US posted after {cutoff}. "
        f"Target roles: {roles_str}. "
        f"Exclude jobs requiring PhD only, US citizenship, security clearance, or 5+ years experience. "
        f"Return ONLY a JSON array. Each object: title, company, location, url, source_board, "
        f"posted_date, remote_type, salary_info, brief_description. No other text."
    )


# ── Gemini API calls with retry ──────────────────────────────────────────


class _GeminiTimeout(Exception):
    pass


def call_gemini_with_retry(
    client: genai.Client,
    contents: list,
    config: types.GenerateContentConfig,
    model: str = DEFAULT_MODEL,
    max_retries: int = 3,
    timeout_seconds: int = 120,
) -> types.GenerateContentResponse:
    import signal

    def _timeout_handler(signum, frame):
        raise _GeminiTimeout(f"Gemini API call timed out after {timeout_seconds}s")

    models_to_try = [model]
    if model != FALLBACK_MODEL:
        models_to_try.append(FALLBACK_MODEL)

    for current_model in models_to_try:
        for attempt in range(max_retries + 1):
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_seconds)
            try:
                result = client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=config,
                )
                signal.alarm(0)
                return result
            except _GeminiTimeout:
                signal.alarm(0)
                if attempt < max_retries:
                    delay = RETRY_DELAY_SECONDS[min(attempt, len(RETRY_DELAY_SECONDS) - 1)]
                    print(f"[TIMEOUT] {current_model} timed out (attempt {attempt + 1}). Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                # Fall through to try next model
                break
            except Exception as e:
                signal.alarm(0)
                err_str = str(e).lower()
                is_transient = (
                    "429" in err_str or "503" in err_str or "rate" in err_str
                    or "quota" in err_str or "resource" in err_str
                    or "unavailable" in err_str or "overloaded" in err_str
                    or "disconnect" in err_str
                )
                if attempt < max_retries and is_transient:
                    delay = RETRY_DELAY_SECONDS[min(attempt, len(RETRY_DELAY_SECONDS) - 1)]
                    print(f"[RETRY] {current_model} error (attempt {attempt + 1}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                if is_transient:
                    break  # Try fallback model
                raise
            finally:
                signal.signal(signal.SIGALRM, old_handler)
        else:
            continue  # All retries exhausted for this model, try next
        # If we broke out of the retry loop, try next model
        if current_model != models_to_try[-1]:
            print(f"[FALLBACK] Switching from {current_model} to {models_to_try[models_to_try.index(current_model) + 1]}")

    raise Exception(f"All models exhausted ({', '.join(models_to_try)}). Last error was transient (503/timeout).")


# ── Phase 1: Discovery via Google Search grounding ───────────────────────


def discover_jobs(
    client: genai.Client,
    queries: list[dict],
    boards: list[str],
    system_prompt: str,
    model: str = DEFAULT_MODEL,
    verbose: bool = False,
) -> list[dict]:
    """Use Gemini + Google Search grounding to discover job listings."""
    all_candidates = []

    SITE_FILTERS = {
        "linkedin": "site:linkedin.com/jobs",
        "indeed": "site:indeed.com/viewjob",
        "glassdoor": "site:glassdoor.com/job-listing",
        "ziprecruiter": "site:ziprecruiter.com/jobs",
        "greenhouse": "site:boards.greenhouse.io",
        "lever": "site:jobs.lever.co",
    }

    # Deduplicate queries by keywords (e.g. "ML Engineer" appears in both General and Remote variants)
    seen_keywords = set()
    unique_queries = []
    for query in queries:
        kw = query["keywords"].lower().strip()
        if kw not in seen_keywords:
            seen_keywords.add(kw)
            unique_queries.append(query)

    if verbose and len(unique_queries) < len(queries):
        print(f"[DEDUP] {len(queries)} queries -> {len(unique_queries)} unique keywords")

    # Search one query × one board per call for fast responses
    total_calls = len(unique_queries) * len(boards)
    call_num = 0

    for query in unique_queries:
        label = query["label"]
        keywords = query["keywords"]

        for board in boards:
            board_lower = board.lower()
            site_filter = SITE_FILTERS.get(board_lower)
            if not site_filter:
                continue

            call_num += 1
            if verbose:
                print(f"[SEARCH] ({call_num}/{total_calls}) {label} | {board}")

            user_msg = (
                f'{keywords} {site_filter}\n\n'
                f'Return a JSON array of job listings. Each object needs: '
                f'title, company, location, url, source_board (set to "{board}"), '
                f'posted_date, remote_type, salary_info, brief_description.'
            )

            try:
                response = call_gemini_with_retry(
                    client,
                    contents=[user_msg],
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        tools=[GOOGLE_SEARCH_TOOL],
                        temperature=0.2,
                    ),
                    model=model,
                    timeout_seconds=60,
                )
            except Exception as e:
                print(f"[ERROR] {label} | {board}: {e}")
                continue

            # Parse the response text for JSON
            resp_text = response.text or ""
            candidates = parse_json_from_response(resp_text)
            if candidates:
                all_candidates.extend(candidates)
                if verbose:
                    print(f"[FOUND] {len(candidates)} candidates")
            elif verbose:
                preview = resp_text[:150].replace("\n", " ")
                print(f"[EMPTY] {preview}...")

            # Brief pause between calls
            time.sleep(1)

    return all_candidates


def parse_json_from_response(text: str) -> list[dict]:
    """Extract a JSON array from Gemini's response text."""
    text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "jobs" in result:
            return result["jobs"]
        return [result] if isinstance(result, dict) else []
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    if "```" in text:
        for block_start in ["```json", "```"]:
            if block_start in text:
                start = text.index(block_start) + len(block_start)
                end = text.index("```", start) if "```" in text[start:] else len(text)
                try:
                    result = json.loads(text[start:end].strip())
                    if isinstance(result, list):
                        return result
                    return [result] if isinstance(result, dict) else []
                except json.JSONDecodeError:
                    continue

    # Try finding array brackets
    if "[" in text:
        start = text.index("[")
        # Find matching closing bracket
        depth = 0
        for j, c in enumerate(text[start:], start):
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : j + 1])
                    except json.JSONDecodeError:
                        break

    return []


# ── Phase 2: Deep extraction via Playwright + Gemini ─────────────────────


def extract_job_details(
    client: genai.Client,
    candidate: dict,
    tool_executor: ToolExecutor,
    model: str = DEFAULT_MODEL,
    verbose: bool = False,
) -> dict | None:
    """Extract full job details for a single candidate.

    For LinkedIn: use Google Search grounding with the specific URL.
    For others: use Playwright to scrape the page, then Gemini to extract.
    """
    url = candidate.get("url", "")
    board = candidate.get("source_board", "").lower()

    if not url:
        return None

    page_text = ""

    if "linkedin.com" in url:
        # Use Google Search to get details about this specific LinkedIn job
        try:
            response = call_gemini_with_retry(
                client,
                contents=[
                    f"Get all available details about this specific job listing: {url}\n"
                    "Extract: full job title, company name, location, salary range, "
                    "full job description, requirements, qualifications, skills, "
                    "experience level, education requirements, benefits, posted date, "
                    "visa sponsorship info, remote/hybrid/onsite status.\n"
                    "Return all details as a JSON object."
                ],
                config=types.GenerateContentConfig(
                    tools=[GOOGLE_SEARCH_TOOL],
                    temperature=0.1,
                ),
                model=model,
            )
            page_text = response.text or ""
        except Exception as e:
            if verbose:
                print(f"[WARN] LinkedIn extraction failed for {url}: {e}")
            return None
    else:
        # Use Playwright to scrape the page
        result = tool_executor.execute("scrape_job_page", {"url": url, "board_name": board})
        if result.get("error"):
            if verbose:
                print(f"[WARN] Scrape failed for {url}: {result['error']}")
            # Fall back to Google Search
            try:
                response = call_gemini_with_retry(
                    client,
                    contents=[f"Find details about this job listing: {url}"],
                    config=types.GenerateContentConfig(
                        tools=[GOOGLE_SEARCH_TOOL],
                        temperature=0.1,
                    ),
                    model=model,
                )
                page_text = response.text or ""
            except Exception:
                return None
        else:
            page_text = result.get("page_text", "")

    if not page_text:
        return None

    # Use Gemini to extract structured data from the page text
    today = datetime.now().strftime("%Y-%m-%d")
    extraction_prompt = (
        f"Extract structured job listing data from the following text.\n"
        f"The job URL is: {url}\n"
        f"The source board is: {candidate.get('source_board', 'Unknown')}\n"
        f"Today's date is: {today}\n\n"
        f"Page content:\n{page_text[:12000]}\n\n"
        "Return a JSON object with these fields (use null for unknown):\n"
        "title, company, location, remote_type (remote/hybrid/onsite), "
        "salary_min (integer), salary_max (integer), salary_type (annual/hourly), "
        "description (full text), requirements (array), nice_to_haves (array), "
        "responsibilities (array), benefits (array), posted_date (ISO-8601), "
        "application_deadline, application_method (direct_apply/email/external_link/easy_apply), "
        "company_size, industry, department, experience_years_min, experience_years_max, "
        "education_required (bachelors/masters/phd/none), "
        "employment_type (full_time/part_time/contract/internship), "
        "seniority_level (intern/entry/mid/senior/lead), "
        "skills_mentioned (array of every skill/tech), tools_mentioned (array), "
        "company_description, team_info, hiring_manager, number_of_applicants, "
        "easy_apply (boolean), visa_sponsorship (yes/no/not_mentioned), "
        "clearance_required (none/basic/secret/top_secret/not_mentioned), "
        "raw_listing_text (brief summary of the listing).\n"
        "Return ONLY the JSON object."
    )

    try:
        response = call_gemini_with_retry(
            client,
            contents=[extraction_prompt],
            config=types.GenerateContentConfig(
                temperature=0.1,
            ),
            model=model,
        )
    except Exception as e:
        if verbose:
            print(f"[WARN] Extraction failed for {url}: {e}")
        return None

    # Parse the structured response
    extracted = parse_json_from_response(response.text or "")
    if extracted and isinstance(extracted, list):
        extracted = extracted[0]
    elif not isinstance(extracted, dict):
        # Build minimal record from discovery data
        extracted = {}

    # Merge discovery data with extracted data (extracted takes priority)
    merged = {**candidate, **{k: v for k, v in extracted.items() if v is not None}}
    merged["url"] = url  # Always keep the original URL
    merged["source_board"] = candidate.get("source_board", "Unknown")

    return merged


# ── Deduplication ────────────────────────────────────────────────────────


def is_duplicate(job: dict, existing_keys: set[str]) -> bool:
    url = job.get("url", "")
    if url and url in existing_keys:
        return True
    return _dedup_key(job) in existing_keys


def merge_into_existing(existing_jobs: list[dict], new_jobs: list[dict]) -> tuple[list[dict], int, int]:
    """Merge new jobs into existing list with deduplication.

    Returns (merged_jobs, new_count, updated_count).
    """
    today = datetime.now().strftime("%Y-%m-%dT00:00:00Z")

    # Build lookup maps
    url_map: dict[str, int] = {}
    key_map: dict[str, int] = {}
    for i, j in enumerate(existing_jobs):
        if j.get("url"):
            url_map[j["url"]] = i
        key_map[_dedup_key(j)] = i

    merged = list(existing_jobs)
    new_count = 0
    updated_count = 0

    for job in new_jobs:
        url = job.get("url", "")
        existing_idx = url_map.get(url)
        if existing_idx is None:
            existing_idx = key_map.get(_dedup_key(job))

        if existing_idx is not None:
            # Update existing record, keep original found_date
            existing = merged[existing_idx]
            original_found_date = existing.get("found_date", today)
            for k, v in job.items():
                if v is not None and v != "" and v != []:
                    existing[k] = v
            existing["found_date"] = original_found_date
            existing["last_seen_date"] = today
            updated_count += 1
        else:
            # Add new job
            job.setdefault("found_date", today)
            job.setdefault("last_seen_date", today)
            if not job.get("id"):
                job["id"] = f"gemini-{uuid.uuid4().hex[:8]}"
            merged.append(job)
            new_count += 1

    return merged, new_count, updated_count


def remove_stale_jobs(jobs: list[dict], max_age_days: int = 21) -> list[dict]:
    """Remove jobs whose posted_date is older than max_age_days."""
    cutoff = datetime.now() - timedelta(days=max_age_days)
    kept = []
    for j in jobs:
        posted = j.get("posted_date")
        if not posted:
            kept.append(j)
            continue
        try:
            posted_dt = datetime.fromisoformat(posted.replace("Z", "+00:00")).replace(tzinfo=None)
            if posted_dt >= cutoff:
                kept.append(j)
        except (ValueError, TypeError):
            kept.append(j)  # Keep if we can't parse the date
    return kept


# ── Output ───────────────────────────────────────────────────────────────


def save_results(
    jobs: list[dict],
    metadata: dict,
    dry_run: bool = False,
) -> None:
    output = {
        "metadata": metadata,
        "jobs": jobs,
    }
    if dry_run:
        print("[DRY RUN] Would write to data/jobs_found.json:")
        print(json.dumps(metadata, indent=2))
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "jobs_found.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"[SAVE] Written {len(jobs)} jobs to {path}")


# ── Main ─────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini-powered job search agent")
    parser.add_argument(
        "--boards",
        type=str,
        default="all",
        help="Comma-separated board names (default: all enabled)",
    )
    parser.add_argument(
        "--queries",
        type=str,
        default="all",
        help="Comma-separated query labels or 'all'",
    )
    parser.add_argument(
        "--max-per-board",
        type=int,
        default=None,
        help="Override max_jobs_per_board",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL}). Try gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash",
    )
    parser.add_argument("--dry-run", action="store_true", help="Search but don't save")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--skip-verify", action="store_true", help="Skip link verification")
    parser.add_argument("--verbose", action="store_true", help="Detailed logging")
    args = parser.parse_args()

    # Load env
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "[ERROR] No API key found. Set GOOGLE_API_KEY in .env or environment.\n"
            "Create .env in project root with:\n  GOOGLE_API_KEY=your_key_here"
        )
        return 2

    start_time = time.time()
    print(f"[SEARCH] Starting Gemini search agent (model: {args.model})...")

    # Load configs
    profile, boards_config, queries_config = load_config()
    existing_jobs = load_existing_jobs()
    existing_keys = build_existing_index(existing_jobs)

    # Filter boards
    all_boards = [b["name"] for b in boards_config["boards"] if b.get("enabled", True)]
    if args.boards != "all":
        requested = [b.strip() for b in args.boards.split(",")]
        all_boards = [b for b in all_boards if b.lower() in [r.lower() for r in requested]]

    # Filter queries
    all_queries = queries_config["queries"]
    if args.queries != "all":
        requested_labels = [q.strip().lower() for q in args.queries.split(",")]
        all_queries = [q for q in all_queries if q["label"].lower() in requested_labels]

    print(f"[CONFIG] {len(all_queries)} queries, {len(all_boards)} boards ({', '.join(all_boards)})")
    print(f"[CONFIG] {len(existing_jobs)} existing jobs loaded for dedup")

    # Initialize components
    client = genai.Client(api_key=api_key)
    browser = BrowserManager(headless=args.headless, rate_limit=profile["pipeline_settings"]["rate_limit_seconds"])
    verifier = LinkVerifier()
    tool_executor = ToolExecutor(browser, verifier)

    errors: list[str] = []
    queries_used: list[str] = []
    boards_searched: list[str] = []

    try:
        # Build system prompt
        system_prompt = build_system_prompt(profile, boards_config, queries_config, len(existing_jobs))

        # Phase 1: Discovery via Google Search
        print("[PHASE 1] Discovering jobs via Google Search...")
        candidates = discover_jobs(
            client, all_queries, all_boards, system_prompt, model=args.model, verbose=args.verbose
        )
        queries_used = [q["label"] for q in all_queries]
        boards_searched = all_boards

        print(f"[DISCOVERY] Found {len(candidates)} candidates total")

        # Deduplicate candidates against existing jobs
        unique_candidates = []
        for c in candidates:
            if not is_duplicate(c, existing_keys):
                unique_candidates.append(c)
                # Add to keys to prevent intra-batch duplicates
                if c.get("url"):
                    existing_keys.add(c["url"])
                existing_keys.add(_dedup_key(c))

        print(f"[DEDUP] {len(unique_candidates)} new unique candidates (filtered {len(candidates) - len(unique_candidates)} duplicates)")

        if not unique_candidates:
            print("[INFO] No new jobs found. Saving existing data with updated metadata.")
            metadata = {
                "search_date": datetime.now().strftime("%Y-%m-%dT00:00:00Z"),
                "queries_used": queries_used,
                "boards_searched": boards_searched,
                "total_found": len(existing_jobs),
                "new_jobs_found": 0,
                "updated_jobs": 0,
                "errors": errors,
            }
            save_results(existing_jobs, metadata, args.dry_run)
            return 0

        # Phase 2: Deep extraction
        print(f"[PHASE 2] Extracting details for {len(unique_candidates)} candidates...")
        detailed_jobs = []
        for idx, candidate in enumerate(unique_candidates):
            if args.verbose:
                print(f"[EXTRACT] ({idx + 1}/{len(unique_candidates)}) {candidate.get('title', '?')} @ {candidate.get('company', '?')}")

            detailed = extract_job_details(client, candidate, tool_executor, model=args.model, verbose=args.verbose)
            if detailed:
                detailed_jobs.append(detailed)
            else:
                errors.append(f"Extraction failed: {candidate.get('title', '?')} @ {candidate.get('company', '?')}")

            # Save progress every 10 extractions
            if len(detailed_jobs) > 0 and len(detailed_jobs) % 10 == 0 and not args.dry_run:
                interim_merged, _, _ = merge_into_existing(existing_jobs, detailed_jobs)
                save_results(interim_merged, {
                    "search_date": datetime.now().strftime("%Y-%m-%dT00:00:00Z"),
                    "queries_used": queries_used,
                    "boards_searched": boards_searched,
                    "total_found": len(interim_merged),
                    "new_jobs_found": len(detailed_jobs),
                    "updated_jobs": 0,
                    "errors": errors + ["Incremental save - extraction in progress"],
                })
                print(f"[SAVE] Incremental save ({len(detailed_jobs)} extracted so far)")

            # Rate limit between extractions
            time.sleep(1)

        print(f"[EXTRACT] {len(detailed_jobs)}/{len(unique_candidates)} extracted successfully")

        # Phase 3: Link verification
        if not args.skip_verify and detailed_jobs:
            print(f"[VERIFY] Verifying {len(detailed_jobs)} job links...")
            verified_jobs = []
            for job in detailed_jobs:
                url = job.get("url", "")
                if not url:
                    continue
                status, details = verifier.verify(url)
                job["link_status"] = status
                if status == "dead":
                    job["link_dead_date"] = datetime.now().strftime("%Y-%m-%dT00:00:00Z")
                    if args.verbose:
                        print(f"[DEAD] {url}: {details}")
                elif status == "verified":
                    verified_jobs.append(job)
                elif status == "redirected":
                    if args.verbose:
                        print(f"[REDIRECT] {url}: {details}")
                    # Still include redirected jobs but flag them
                    verified_jobs.append(job)

            print(f"[VERIFY] {len(verified_jobs)} verified, {len(detailed_jobs) - len(verified_jobs)} dead/removed")
            detailed_jobs = verified_jobs

        # Merge with existing
        merged_jobs, new_count, updated_count = merge_into_existing(existing_jobs, detailed_jobs)

        # Remove stale jobs
        merged_jobs = remove_stale_jobs(merged_jobs)

        # Save
        metadata = {
            "search_date": datetime.now().strftime("%Y-%m-%dT00:00:00Z"),
            "queries_used": queries_used,
            "boards_searched": boards_searched,
            "total_found": len(merged_jobs),
            "new_jobs_found": new_count,
            "updated_jobs": updated_count,
            "errors": errors,
        }
        save_results(merged_jobs, metadata, args.dry_run)

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Saving progress...")
        metadata = {
            "search_date": datetime.now().strftime("%Y-%m-%dT00:00:00Z"),
            "queries_used": queries_used,
            "boards_searched": boards_searched,
            "total_found": len(existing_jobs),
            "new_jobs_found": 0,
            "updated_jobs": 0,
            "errors": errors + ["Interrupted by user"],
        }
        save_results(existing_jobs, metadata, args.dry_run)
        return 1

    except Exception as e:
        print(f"[FATAL] {e}")
        errors.append(f"Fatal: {e}")
        # Save what we have
        metadata = {
            "search_date": datetime.now().strftime("%Y-%m-%dT00:00:00Z"),
            "queries_used": queries_used,
            "boards_searched": boards_searched,
            "total_found": len(existing_jobs),
            "new_jobs_found": 0,
            "updated_jobs": 0,
            "errors": errors,
        }
        save_results(existing_jobs, metadata, args.dry_run)
        return 1

    finally:
        browser.close()
        verifier.close()

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print(f"\n[SUMMARY]")
    print(f"  Boards searched: {', '.join(boards_searched)}")
    print(f"  Queries used: {len(queries_used)}")
    print(f"  New jobs added: {new_count}")
    print(f"  Jobs updated: {updated_count}")
    print(f"  Total in database: {len(merged_jobs)}")
    if errors:
        print(f"  Errors: {len(errors)}")
    print(f"  Duration: {minutes}m {seconds}s")
    print(f"[DONE]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
