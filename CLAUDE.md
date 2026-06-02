# Job Application Automation Pipeline

This project automates the job application process using a multi-agent pipeline. Each agent is a specialist that handles one stage of the pipeline. Designed for both sequential execution and `claude cowork` team mode. Runs daily with deduplication.

## Project Overview

Automated job application system. User profile loaded from `config/user_profile.json`. See `config/user_profile.example.json` for setup instructions and a sample configuration.

## Pipeline Architecture

```
config/ (read by all agents)
    │
    ▼
[cleaner] ──▶ data/jobs_found.json (removes stale jobs, archives to jobs_archived.json)
    │
    ▼
[search]  ──▶ data/jobs_found.json (skips already-applied URLs)
    │
    ▼
[careers] ──▶ data/company_careers.json (URL lookup ONLY for new companies)
    │
    ▼
[score]   ──▶ data/jobs_scored.json
    │
    ▼
[save]    ──▶ data/pipeline_log.json + data/run_summary.md (local backup only)
    ┊
    ┊       ── user reviews data/run_summary.md, says "apply" ──
    ┊
    ▼
[apply]   ──▶ For each job: tailor → fill form → STOP for user to submit
              data/tailored_materials/{company}/{job_id}_{role}_resume.md + .pdf
              data/tailored_materials/{company}/{job_id}_{role}_cover_letter.md + .pdf
              data/tailored_tracker.json
              data/applications_submitted.json + data/screenshots/
    │
    ▼
[verify]  ──▶ data/applications_verified.json + data/verification_summary.md
    │
    ▼
[save]    ──▶ data/pipeline_log.json + data/run_summary.md
```

## Trigger Words

| Trigger | Action |
|---------|--------|
| **"start search"** | Run cleaner → search → careers → score → save. Full end-to-end: dashboard is up-to-date when it finishes. See coordinated workflow below. |
| **"score"** | Invoke the **score** agent standalone (usually not needed — "start search" already scores) |
| **"apply"** | Invoke the **apply** agent -- it tailors + fills forms, then STOPS for user to submit |
| **"verify"** | Invoke the **verify** agent |
| **"save"** | Invoke the **save** agent standalone (usually not needed — "start search" already saves) |

**Note:** There is no separate "tailor" trigger. The apply agent tailors materials on-the-fly for each job right before filling the application form. This avoids unnecessary tailoring for jobs the user might skip.

The user reviews the database between each stage before proceeding.

## "start search" Coordinated Workflow

When the user says "start search", run these five agents **sequentially** end-to-end. `data/run_summary.md` is fresh when the pipeline finishes:

1. **Cleaner (Phase 1)**: Prunes `data/jobs_found.json` of jobs with `posted_date` older than 14 days (unless `application_status == "applied"`). Archives them to `data/jobs_archived.json`. Keeps downstream agents from wasting tokens on stale listings.
2. **Search (Phase 2)**: Runs Vertex AI Search (via `scripts/google_search.py`) to discover URLs. Skips any URL already marked `applied`. Extracts full details only for new URLs and writes to `data/jobs_found.json`.
3. **Careers (Phase 3)**: For any companies in `data/jobs_found.json` not yet in `data/company_careers.json`, looks up their official careers URL and caches it. Does NOT scan career pages for jobs — only maintains the company URL cache.
4. **Score (Phase 4)**: Scores and ranks only the new/updated jobs from Phase 2 against the user's profile. Preserves existing `application_status` values. Writes to `data/jobs_scored.json`.
5. **Save (Phase 5)**: Writes `data/pipeline_log.json` (append) and `data/run_summary.md` (overwrite) — local backup only, no external services. This is what the user reviews to see the new jobs.

**`apply` and `verify` are NOT auto-run** — those still require user judgment (which job to apply to, reviewing filled forms before submit). After "start search" finishes, the user reviews the ranked dashboard, then says `apply` for jobs they want to pursue.

## Agent Roster

| Agent | Purpose | Model | When to Invoke |
|-------|---------|-------|----------------|
| **cleaner** | Remove stale jobs (>14 days old, not applied) from jobs_found.json; archive them | haiku | User says "start search" (Phase 1) |
| **search** | Find job listings via Vertex AI Search + extraction; skip already-applied URLs | sonnet | User says "start search" (Phase 2) |
| **careers** | Look up career page URLs for NEW companies only; does NOT scan for jobs | haiku | User says "start search" (Phase 3) |
| **score** | Score and rank jobs by fit against user profile | opus | User says "score" |
| **apply** | Tailors materials on-the-fly + fills application forms + STOPS for user to submit | opus | User says "apply" |
| **verify** | Confirm submissions were received | sonnet | User says "verify" |
| **save** | Write local backup logs (pipeline_log.json + run_summary.md) | haiku | Auto-runs at end of "start search" |

**Note:** The tailor agent (`tailor.md`) still exists as a standalone agent but is now primarily used BY the apply agent internally. The apply agent tailors materials just-in-time for each job before filling the form.

## Daily Run Behavior

This pipeline is designed to run **daily**:
- **Cleaner**: Prunes `data/jobs_found.json` of jobs older than 14 days (preserves applied jobs). Archives removed jobs to `data/jobs_archived.json`.
- **Search**: Finds new jobs via Vertex AI Search. Skips URLs where `application_status == "applied"`. Deduplicates by job URL or (title + company + location). Updates existing entries with new data. Adds `last_seen_date`.
- **Careers**: Only looks up career page URLs for NEW companies (ones not yet in `data/company_careers.json`). Does NOT scan career pages for job listings.
- **Score**: Only scores new/updated jobs. Preserves `application_status` for previously scored jobs.
- **Apply**: After applying, checks the job site to update `application_status` to "applied".
- **Save**: Appends a run-summary entry to `pipeline_log.json`; overwrites `run_summary.md` with the current snapshot.

## Data Schemas

### jobs_found.json
```json
{
  "metadata": {
    "search_date": "ISO-8601",
    "queries_used": ["string"],
    "boards_searched": ["string"],
    "total_found": 0,
    "new_jobs_found": 0,
    "updated_jobs": 0,
    "errors": ["string"]
  },
  "jobs": [
    {
      "id": "uuid or board-specific ID",
      "title": "string",
      "company": "string",
      "location": "string",
      "remote_type": "remote|hybrid|onsite",
      "salary_min": null,
      "salary_max": null,
      "salary_type": "annual|hourly|null",
      "description": "string (full text)",
      "requirements": ["string"],
      "nice_to_haves": ["string"],
      "responsibilities": ["string"],
      "benefits": ["string"],
      "url": "string (application URL)",
      "source_board": "string",
      "posted_date": "ISO-8601|null",
      "application_deadline": "ISO-8601|null",
      "application_method": "direct_apply|email|external_link|easy_apply",
      "company_size": "string|null",
      "industry": "string|null",
      "department": "string|null",
      "experience_years_min": null,
      "experience_years_max": null,
      "education_required": "bachelors|masters|phd|none|null",
      "employment_type": "full_time|part_time|contract|internship",
      "seniority_level": "intern|entry|mid|senior|lead|null",
      "skills_mentioned": ["string"],
      "tools_mentioned": ["string"],
      "company_description": "string|null",
      "team_info": "string|null",
      "hiring_manager": "string|null",
      "number_of_applicants": "string|null",
      "easy_apply": false,
      "visa_sponsorship": "yes|no|not_mentioned",
      "clearance_required": "none|basic|secret|top_secret|not_mentioned",
      "company_careers_url": "string|null",
      "company_ats_platform": "string|null",
      "found_date": "ISO-8601",
      "last_seen_date": "ISO-8601",
      "raw_listing_text": "string"
    }
  ]
}
```

### company_careers.json
```json
{
  "metadata": {
    "lookup_date": "ISO-8601",
    "total_companies": 0,
    "total_found": 0
  },
  "companies": [
    {
      "company_name": "string",
      "careers_url": "string|null",
      "ats_platform": "string",
      "direct_search_url": "string|null",
      "verified": true,
      "notes": "string|null"
    }
  ]
}
```

### jobs_scored.json
```json
{
  "metadata": {
    "scoring_date": "ISO-8601",
    "total_scored": 0,
    "newly_scored": 0,
    "re_scored": 0,
    "skipped_unchanged": 0,
    "threshold_used": 60,
    "jobs_above_threshold": 0
  },
  "scored_jobs": [
    {
      "job_id": "string",
      "title": "string",
      "company": "string",
      "location": "string",
      "remote_type": "string",
      "url": "string",
      "overall_score": 0,
      "breakdown": {
        "skill_match": 0,
        "experience_match": 0,
        "education_match": 0,
        "location_match": 0,
        "salary_match": 0,
        "culture_fit": 0
      },
      "matched_skills": ["string"],
      "missing_skills": ["string"],
      "recommendation": "strong_apply|apply|maybe|skip",
      "reasoning": "string",
      "scored_date": "ISO-8601",
      "application_status": "not_applied|applied|needs_manual_review|skipped"
    }
  ]
}
```

### applications_submitted.json
```json
{
  "metadata": {
    "submission_date": "ISO-8601",
    "total_attempted": 0,
    "total_succeeded": 0,
    "total_failed": 0
  },
  "applications": [
    {
      "job_id": "string",
      "company": "string",
      "title": "string",
      "status": "submitted|failed|needs_manual_review",
      "method": "direct_apply|email|manual",
      "submitted_at": "ISO-8601|null",
      "confirmation_id": "string|null",
      "screenshot_path": "string|null",
      "resume_used": "string (file path)",
      "cover_letter_used": "string (file path)",
      "error_details": "string|null",
      "notes": "string|null"
    }
  ]
}
```

### applications_verified.json
```json
{
  "metadata": {
    "verification_date": "ISO-8601",
    "total_verified": 0,
    "total_unverified": 0
  },
  "verifications": [
    {
      "job_id": "string",
      "company": "string",
      "verification_status": "confirmed|unconfirmed|email_received|portal_shows_applied",
      "verification_method": "email_check|portal_check|confirmation_page|screenshot_review",
      "evidence": "string",
      "verified_at": "ISO-8601"
    }
  ]
}
```

## Tailored Materials Folder Structure

```
data/tailored_materials/
├── ness_digital_engineering/
│   └── senior_data_engineer/
│       ├── resume.md
│       ├── {FirstName}_{LastName}_Senior_Data_Engineer.pdf
│       ├── cover_letter.md
│       └── {FirstName}_{LastName}_Senior_Data_Engineer_Cover_Letter.pdf
└── ...
```

Pattern: `data/tailored_materials/{company_slug}/{role_slug}/{FirstName}_{LastName}_{Role_Short}.pdf`

Where `{FirstName}` and `{LastName}` come from `personal.first_name` and `personal.last_name` in `config/user_profile.json`.

## Key File Locations

| File | Purpose |
|------|---------|
| `files/{FirstName}{LastName}_Resume.pdf` | Original resume for uploading |
| `files/resume_base.md` | Markdown resume for tailoring (copy from `resume_base_example.md`) |
| `files/portfolio_details.md` | Extended portfolio details: additional experience, project demos, metrics |
| `files/cover_letter_template.md` | Base cover letter template |
| `config/user_profile.json` | All user preferences and personal info (copy from `user_profile.example.json`) |
| `config/job_boards.json` | Job board URLs and search configs |
| `config/search_queries.json` | Pre-built search query templates |

## Login Status

- **LinkedIn**: Do NOT use Playwright to log in or browse. Use WebSearch only for LinkedIn job listings. LinkedIn blocks automation and may lock the account.
- **Indeed, Glassdoor**: Use Playwright if needed, but prefer WebSearch. If login is required, mark as `needs_manual_review`.
- **ZipRecruiter, Greenhouse, Lever**: No login needed. Playwright works fine.

## Critical Rules

1. **Never click Submit** -- The apply agent fills forms but NEVER clicks Submit/Apply. The user reviews the browser and clicks Submit themselves. Non-negotiable.
2. **Rate limiting** -- Wait 3-5 seconds between job board page loads. Wait 30 seconds between application submissions.
3. **Error recovery** -- If an application fails, log the error and continue. Never stop the pipeline on a single failure.
4. **Data preservation** -- On daily runs, update existing records. Never overwrite with less data.
5. **Privacy** -- Never log passwords or sensitive credentials.
6. **Keyword Matching** -- Tailored resumes must match at least 90% of keywords from the job description. Rephrase and add skills as needed to hit this target.
7. **Account creation allowed** -- When a job portal requires login/signup, use the credentials in `config/user_profile.json` (`personal.job_portal_credentials`) to create an account or log in.
8. **CAPTCHA handling** -- If a CAPTCHA appears, screenshot it and **notify the user immediately**. Do not attempt to solve it.
9. **Resume upload path** -- Always use the tailored PDF from `data/tailored_materials/{company}/{role}/`. The base resume PDF should be placed at `files/{FirstName}{LastName}_Resume.pdf` matching `personal.first_name` + `personal.last_name` in `config/user_profile.json`.
10. **Apply from career pages only** -- Always apply through the company's official career page or ATS (Greenhouse, Lever, Workday, Ashby), never through job board aggregators (Indeed, LinkedIn, Glassdoor, ZipRecruiter). Direct applications carry more weight.
11. **Max applications per run** -- Respect `max_applications_per_run` from config.
12. **Application status tracking** -- After applying to a job, check the job site to confirm and update `application_status` to "applied".
13. **Deduplication** -- On daily runs, match by job URL or (title + company + location). Update existing records, don't create duplicates.
