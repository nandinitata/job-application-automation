# Setup Guide

## Step 1: Clone and Install

```bash
git clone https://github.com/nandinitata/job-application-automation.git
cd job-application-automation

pip install -r requirements.txt
playwright install chromium
```

## Step 2: Configure API Keys (.env)

```bash
cp .env.example .env
```

Edit `.env` and fill in:

### Google API Key
1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Create a new API key
3. Set `GOOGLE_API_KEY=your_key_here`

### Google Custom Search Engine (CSE)
1. Go to [programmablesearchengine.google.com](https://programmablesearchengine.google.com/)
2. Create a new search engine (add `*.linkedin.com`, `*.indeed.com`, `*.naukri.com` etc. as sites to search)
3. Get the CSE ID from the control panel
4. Set `GOOGLE_CSE_ID=your_cse_id_here`

### Google Cloud Project (Vertex AI Search)
1. Create a project at [console.cloud.google.com](https://console.cloud.google.com/)
2. Enable the Discovery Engine API: `gcloud services enable discoveryengine.googleapis.com`
3. Set `GCP_PROJECT_ID=your-project-id`

## Step 3: Configure Your Profile

```bash
cp config/user_profile.example.json config/user_profile.json
```

Edit `config/user_profile.json` — replace all `YOUR_*` placeholders:

| Field | Description |
|-------|-------------|
| `personal.first_name` / `personal.last_name` | Your name (used in PDF filenames and form filling) |
| `personal.email` | Your primary email for job applications |
| `personal.phone` | Format: `+91-XXXXXXXXXX` for India |
| `personal.linkedin_url` | Your LinkedIn profile URL |
| `personal.notice_period` | e.g., `"30 days"`, `"60 days"`, `"Immediately"` |
| `personal.job_portal_credentials.password` | Password for creating accounts on job portals |
| `preferences.target_roles` | List of job titles to search for |
| `preferences.salary_min` / `salary_max` | In INR (e.g., `2500000` = ₹25 LPA) |
| `preferences.salary_currency` | `"INR"` for India |
| `preferences.experience_level` | `["senior"]` for senior-only targeting |
| `preferences.location_preferences.preferred_locations` | Cities you're open to |

## Step 4: Add Your Resume

```bash
cp files/resume_base_example.md files/resume_base.md
cp files/portfolio_details_example.md files/portfolio_details.md
cp files/cover_letter_template_example.md files/cover_letter_template.md
```

Replace the example content with your actual information. Keep the same markdown structure — the tailoring agent and PDF generator depend on it.

Also place your current resume PDF at:
```
files/{YourFirstName}{YourLastName}_Resume.pdf
```

## Step 5: Set Up Google Vertex AI Search

This is what powers the job discovery. One-time setup:

```bash
# Authenticate with GCP
gcloud auth application-default login

# Create a Discovery Engine data store (paste your project ID)
gcloud alpha discovery-engine data-stores create \
  --project=YOUR_PROJECT_ID \
  --location=global \
  --collection=default_collection \
  --data-store-id=job-boards-search \
  --display-name="Job Boards Search" \
  --type=SITE_SEARCH

# The search engine ID will be used by scripts/google_search.py automatically
```

Alternatively, create it via the GCP Console under "Discovery Engine" → "Apps" → "Create App".

## Step 6: Customize Search Queries

Edit `config/search_queries.json` to match your target roles:

```json
{
  "queries": [
    "Senior Data Engineer Databricks Bengaluru",
    "Lead Data Engineer Microsoft Fabric India",
    "Senior Databricks Engineer remote India"
  ]
}
```

## Step 7: Initialize Data Directory

```bash
mkdir -p data/screenshots data/tailored_materials
cp data/portal_accounts.example.json data/portal_accounts.json
```

## Step 8: Open Claude Code and Run

```bash
claude
```

Then type: **`start search`**

The pipeline will run automatically:
1. Clean stale jobs
2. Search for new listings matching your target roles
3. Cache company career page URLs
4. Score and rank all jobs
5. Write `data/run_summary.md` with the ranked dashboard

Review `data/run_summary.md`, then type **`apply`** for the jobs you want to pursue.

## Troubleshooting

**"GCP_PROJECT_ID not set"** → Check your `.env` file has `GCP_PROJECT_ID=your-project-id`

**"No jobs found"** → Try broadening your `config/search_queries.json` queries, or check your CSE is indexing the right job boards

**"PDF generation failed"** → Make sure `pdflatex` is installed: `brew install --cask mactex` (Mac) or `sudo apt-get install texlive-full` (Linux)

**CAPTCHA on a job board** → The agent will screenshot and notify you. Solve it manually in the browser, then tell Claude to continue.
