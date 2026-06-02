# Job Application Automation Pipeline

A multi-agent job application automation system built with Claude AI agents, Python, and Playwright. Automates job discovery, scoring, resume tailoring, and application form-filling — while keeping **you in control of the final submit**.

## Features

- **Multi-agent pipeline**: search → score → tailor → apply → verify
- **Vertex AI Search** for superior job discovery across LinkedIn, Indeed, Naukri, Glassdoor, Greenhouse, Lever
- **ATS-optimized resume tailoring** with 90%+ keyword matching
- **Automatic form-filling** via Playwright browser automation
- **Human-in-the-loop**: agent fills forms, YOU click Submit — never auto-submits
- **Local dashboard** for reviewing and ranking scored jobs
- **Daily deduplication**: runs every day without creating duplicate entries

## Pipeline Architecture

```
config/ (read by all agents)
    │
    ▼
[cleaner] ──▶ data/jobs_found.json   (removes stale jobs >14 days)
    │
    ▼
[search]  ──▶ data/jobs_found.json   (Vertex AI Search + Playwright extraction)
    │
    ▼
[careers] ──▶ data/company_careers.json  (career URL cache for apply agent)
    │
    ▼
[score]   ──▶ data/jobs_scored.json  (ranked by fit score)
    │
    ▼
[save]    ──▶ data/run_summary.md    (human-readable dashboard)

         ── you review run_summary.md, say "apply" ──

[apply]   ──▶ tailor → fill form → STOP (you click Submit)
[verify]  ──▶ confirms submissions via email/portal
```

## Prerequisites

- Python 3.11+
- [Claude Code CLI](https://claude.ai/code) with an Anthropic API key
- Node.js (for Playwright)
- Google Cloud account (for Vertex AI Search / Discovery Engine)
- A Google API key + Custom Search Engine ID (fallback search)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/nandinitata/job-application-automation.git
cd job-application-automation

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Playwright browser
playwright install chromium

# 4. Set up secrets
cp .env.example .env
# Edit .env with your API keys

# 5. Set up your profile
cp config/user_profile.example.json config/user_profile.json
# Edit config/user_profile.json with your details

# 6. Add your resume
cp files/resume_base_example.md files/resume_base.md
# Replace with your actual resume content

# 7. Open Claude Code and say:
#    start search
```

See [SETUP.md](SETUP.md) for the full step-by-step configuration guide.

## Trigger Words

| Say this | What happens |
|----------|-------------|
| `start search` | Runs the full pipeline: cleaner → search → careers → score → save |
| `apply` | For each top-scored job: tailor materials → fill form → **stop for you to submit** |
| `verify` | Check which applications were confirmed received |
| `score` | Re-score jobs (usually not needed — "start search" already scores) |
| `save` | Write pipeline log and run summary (usually not needed — auto-runs) |

## Sample Configuration

This repo includes a sample configuration for a **Senior Data Engineer** with 5 years Databricks + 2 years Microsoft Fabric experience targeting senior roles in India. See:

- `config/user_profile.example.json` — profile template
- `files/resume_base_example.md` — sample resume
- `data/sample_jobs_found.json` — 5 sample job listings (real companies from Indeed India)
- `data/sample_jobs_scored.json` — scored versions showing fit analysis

## Configuration

### `config/user_profile.json`

Key fields:
- `personal.first_name`, `personal.last_name` — used in PDF naming and form filling
- `personal.email`, `personal.phone` — auto-filled on application forms
- `personal.notice_period` — filled on Indian job portals
- `preferences.target_roles` — what the search agent looks for
- `preferences.experience_level` — `["senior"]` for senior-only targeting
- `preferences.salary_min/max` — for scoring and form fields
- `preferences.salary_currency` — `"INR"` for India
- `preferences.location_preferences` — cities you're open to

### Google Vertex AI Search Setup

The search agent uses Google's Vertex AI Search (Discovery Engine) for high-quality job discovery. [SETUP.md](SETUP.md) has the full GCP setup steps.

## Security

- `config/user_profile.json` is **gitignored** — your personal details never leave your machine
- `data/portal_accounts.json` is **gitignored** — job portal passwords stay local
- `data/` files (jobs, applications, screenshots) are **gitignored** — your application history is private
- `files/*.pdf` are **gitignored** — your resume PDFs stay local
- Only add `.env` to `.gitignore` — never commit API keys

## License

MIT
