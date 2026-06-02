#!/usr/bin/env python3
"""Vertex AI Search helper for job discovery.

Uses Google's Vertex AI Search (Discovery Engine) for fast, reliable job listing
discovery across configured job board sites. Returns structured JSON results
that the Claude search agent can process.

Setup (already done):
    1. Enable Discovery Engine API: gcloud services enable discoveryengine.googleapis.com
    2. Authenticate: gcloud auth application-default login
    3. Data store "job-boards-search" and engine "job-search-engine" are pre-configured
       with sites: linkedin, indeed, glassdoor, ziprecruiter, greenhouse, lever

Usage:
    python3 scripts/google_search.py "Machine Learning Engineer"
    python3 scripts/google_search.py "Data Scientist entry level" --num 10
    python3 scripts/google_search.py --from-config
    python3 scripts/google_search.py --from-config --num 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from google.cloud import discoveryengine_v1 as discoveryengine

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Vertex AI Search configuration
import os
GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
LOCATION = "global"
ENGINE_ID = "job-search-engine"


def get_serving_config() -> str:
    return (
        f"projects/{GCP_PROJECT}/locations/{LOCATION}/collections/"
        f"default_collection/engines/{ENGINE_ID}/servingConfigs/default_config"
    )


def is_specific_job_url(url: str) -> bool:
    """Return True only if URL looks like a specific job posting.

    Rejects aggregator/category/search pages that don't correspond to a single
    job (e.g., "Entry Level ML Jobs in NYC"). These dominate Vertex AI's
    results because they have strong SEO, but they're useless for extraction.
    """
    url_lower = url.lower()

    # Indeed: ONLY /viewjob?jk=XXX or /rc/clk are specific
    if "indeed.com" in url_lower:
        if "/viewjob" in url_lower and "jk=" in url_lower:
            return True
        if "/rc/clk" in url_lower and "jk=" in url_lower:
            return True
        return False  # q-*.html, career-advice, hire, /jobs?q=*, etc.

    # LinkedIn: /jobs/view/{id} OR /jobs/{slug}-{9+digit_id}
    if "linkedin.com" in url_lower:
        if "/jobs/view/" in url_lower:
            return True
        if re.search(r"/jobs/[^/?]+-(\d{9,})(/?|\?|$)", url_lower):
            return True
        return False  # /jobs/search, /jobs/collections, /jobs/*-jobs-in-*

    # Greenhouse: must have /jobs/{numeric_id}
    if "greenhouse.io" in url_lower:
        return bool(re.search(r"/jobs/\d+", url_lower))

    # Lever: {company}/{uuid-style-id}
    if "lever.co" in url_lower:
        return bool(re.search(
            r"lever\.co/[^/]+/[0-9a-f]{8}-[0-9a-f]{4}",
            url_lower
        ))

    # Glassdoor: /job-listing/ with a jobListingId= param or JV number
    if "glassdoor.com" in url_lower:
        if "jobListingId=" in url or re.search(r"-jv[^/]*\d+", url_lower):
            return True
        return False  # /Job/{role}-jobs-*, /partner/*

    # ZipRecruiter: /jobs/{company-slug}-{hash}/{job-hash}
    if "ziprecruiter.com" in url_lower:
        if "/jobs/search" in url_lower:
            return False
        if re.search(r"/jobs/[^/]+/[a-f0-9]{10,}", url_lower):
            return True
        return False

    # Jobright: /jobs/{slug-id} are specific; /jobs/recommend, /jobs/liked, etc. are aggregator pages
    if "jobright.ai" in url_lower:
        if re.search(r"/jobs/(recommend|liked|applied|external|search)(/|$|\?)", url_lower):
            return False
        if re.search(r"/jobs/[^/?]+", url_lower):
            return True
        return False

    # Unknown domain — keep (might be a company careers page)
    return True


def search(query: str, num_results: int = 25, specific_only: bool = False) -> list[dict]:
    """Search job boards via Vertex AI Search.

    Returns results sorted with specific job listings first, then aggregator
    pages (which the search agent can mine for individual job URLs). Each
    result is tagged with `is_specific` so downstream code can prioritize.

    If `specific_only=True`, aggregator pages are dropped entirely.
    """
    client = discoveryengine.SearchServiceClient()

    # Over-fetch so specific listings aren't drowned by aggregators
    fetch_count = min(num_results * 4, 100)

    request = discoveryengine.SearchRequest(
        serving_config=get_serving_config(),
        query=query,
        page_size=fetch_count,
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True
            ),
        ),
        query_expansion_spec=discoveryengine.SearchRequest.QueryExpansionSpec(
            condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO,
        ),
        spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
            mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO
        ),
    )

    try:
        page_result = client.search(request)
    except Exception as e:
        print(f"[ERROR] Search failed: {e}", file=sys.stderr)
        return []

    specific_results = []
    aggregator_results = []

    for result in page_result:
        doc = result.document
        data = dict(doc.derived_struct_data) if doc.derived_struct_data else {}

        url = data.get("link", "")
        if not url:
            continue

        snippets = data.get("snippets", [])
        snippet_text = snippets[0].get("snippet", "") if snippets else ""
        is_specific = is_specific_job_url(url)

        entry = {
            "title": data.get("title", ""),
            "url": url,
            "snippet": snippet_text,
            "source_board": detect_board(url),
            "display_link": data.get("displayLink", ""),
            "is_specific_job": is_specific,
        }

        if is_specific:
            specific_results.append(entry)
        else:
            aggregator_results.append(entry)

    # Specific listings first — these are the high-value results
    if specific_only:
        combined = specific_results
    else:
        combined = specific_results + aggregator_results

    print(
        f"  [STATS] {len(specific_results)} specific, "
        f"{len(aggregator_results)} aggregators",
        file=sys.stderr,
    )

    return combined[:num_results]


def detect_board(url: str) -> str:
    """Detect which job board a URL belongs to."""
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "LinkedIn"
    elif "indeed.com" in url_lower:
        return "Indeed"
    elif "glassdoor.com" in url_lower:
        return "Glassdoor"
    elif "ziprecruiter.com" in url_lower:
        return "ZipRecruiter"
    elif "greenhouse.io" in url_lower:
        return "Greenhouse"
    elif "lever.co" in url_lower:
        return "Lever"
    return "Unknown"


def search_from_config(num_results: int = 25, specific_only: bool = False) -> list[dict]:
    """Run all queries from config/search_queries.json."""
    config_path = PROJECT_ROOT / "config" / "search_queries.json"
    with open(config_path) as f:
        queries = json.load(f)["queries"]

    # Deduplicate by keywords
    seen = set()
    unique_queries = []
    for q in queries:
        kw = q["keywords"].lower().strip()
        if kw not in seen:
            seen.add(kw)
            unique_queries.append(q)

    all_results = []
    total = len(unique_queries)

    for i, query in enumerate(unique_queries, 1):
        label = query["label"]
        keywords = query["keywords"]
        print(f"[SEARCH] ({i}/{total}) {label}", file=sys.stderr)

        results = search(keywords, num_results=num_results, specific_only=specific_only)
        if results:
            print(f"  [FOUND] {len(results)} results", file=sys.stderr)
            all_results.extend(results)
        else:
            print(f"  [EMPTY] No results", file=sys.stderr)

        # Brief pause between queries
        time.sleep(0.3)

    return all_results


def main():
    parser = argparse.ArgumentParser(description="Vertex AI Search for job discovery")
    parser.add_argument("query", nargs="?", help="Search query keywords")
    parser.add_argument("--from-config", action="store_true",
                        help="Run all queries from config/search_queries.json")
    parser.add_argument("--num", type=int, default=25,
                        help="Max results per query (default: 25). Results are sorted specific-jobs first, then aggregators. We over-fetch up to 100 from Vertex.")
    parser.add_argument("--specific-only", action="store_true",
                        help="Drop aggregator/category pages — return only specific job listings")
    args = parser.parse_args()

    if args.from_config:
        results = search_from_config(num_results=args.num, specific_only=args.specific_only)
    elif args.query:
        results = search(args.query, num_results=args.num, specific_only=args.specific_only)
    else:
        parser.print_help()
        return 1

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for r in results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique.append(r)

    # Output JSON to stdout
    print(json.dumps(unique, indent=2))
    print(f"\n[TOTAL] {len(unique)} unique results", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
