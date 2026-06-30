# Job Auto-Applier

A daily CLI tool that reads a config of personal info and Greenhouse job posting URLs, uses Claude to score fit and draft cover letters, then auto-fills and submits applications via Playwright. Every result is logged to a Google Sheet.

Works for any field — configure your `roles` and `locations` to match what you're targeting.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # fill in your keys
```

## Configuration

Edit `config.yaml`:

| Key | Description |
|-----|-------------|
| `person:` | Your name, email, phone, location, LinkedIn, GitHub, resume PDF path, background bio |
| `roles:` | Job titles and skill keywords used for fit scoring (any domain) |
| `locations:` | Only apply to jobs whose location contains one of these strings. Empty list = no filter |
| `cover_letter:` | `auto` (only when required) \| `never` \| `always` |
| `fit_threshold:` | Minimum Claude fit score 0–10 to attempt an application |
| `spreadsheet_id:` | Google Sheet ID for tracking (see below). Leave `""` to disable |
| `allowlist:` | Greenhouse posting URLs to process today |

## Daily Usage

```bash
# Add URLs to allowlist in config.yaml, then:
python runner.py --dry-run   # fill forms but don't submit (for inspection)
python runner.py             # submit all new jobs in the allowlist
python runner.py --url https://boards.greenhouse.io/company/jobs/123  # single URL
```

## Robotics Job Boards

These sites are worth checking daily for Greenhouse postings to add to your `allowlist`:

| Board | Focus | Notes |
|-------|-------|-------|
| [careersinrobotics.com](https://careersinrobotics.com) | Broad robotics & automation | 3,200+ curated jobs, browsable by role/industry |
| [roboticshire.net](https://roboticshire.net) | Robotics & automation | Strong on ROS, AMR, drone, surgical roles |
| [greatrobots.ai](https://greatrobots.ai) | Robotics & autonomy | Lists Figure AI, Anduril, Applied Intuition, Shield AI |
| [robots.jobs](https://robots.jobs) | AI + robotics | 100% focused on AI/robotics |
| [LinkedIn Jobs](https://linkedin.com/jobs) | All fields | Highest volume; filter by "Greenhouse" in the apply flow |

Most postings on these boards link directly to Greenhouse URLs — paste those into your `allowlist`.

## Google Sheets Setup

Each run appends a row to your sheet with: Date, Title, Company, Location, URL, Status, Fit Score, Reason.

**1. Create a Google Cloud project and enable the Sheets API**

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a new project (e.g. `job-applier`)
2. Go to **APIs & Services → Enable APIs** → search for **Google Sheets API** → Enable it

**2. Create a Service Account**

1. Go to **APIs & Services → Credentials → Create Credentials → Service Account**
2. Give it any name (e.g. `job-applier-bot`), click through to finish
3. Click the service account → **Keys → Add Key → Create new key → JSON**
4. Download the JSON file; save it somewhere safe (e.g. `~/.config/job-applier-sa.json`)

**3. Create your Google Sheet**

1. Go to [sheets.google.com](https://sheets.google.com) and create a new blank spreadsheet
2. Name it anything (e.g. `Job Applications`)
3. Copy the spreadsheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID_HERE/edit
   ```

**4. Share the sheet with the service account**

1. Open the sheet → **Share**
2. Paste the service account's email address (found in the JSON file under `"client_email"`)
3. Give it **Editor** access → Share

**5. Add to your `.env` and `config.yaml`**

`.env`:
```
GOOGLE_SERVICE_ACCOUNT_JSON=/home/you/.config/job-applier-sa.json
```

`config.yaml`:
```yaml
spreadsheet_id: "SPREADSHEET_ID_HERE"
```

That's it — the sheet will be created and the header row written automatically on first run.

## How It Works

1. For each URL in `allowlist` not already in `applied.json`:
   - Scrapes the Greenhouse job page (title, description, location, form fields)
   - Checks location against `locations` filter — skips if no match
   - Claude scores fit against `roles` and `background` — skips if below `fit_threshold`
   - Playwright fills standard fields (name, email, phone, location, resume)
   - If the cover letter field is required (and `cover_letter != never`), Claude writes one
   - Claude answers any custom free-text questions using your background
   - Submits the form (or pauses for 5s in `--dry-run` mode)
2. Result recorded in `applied.json` (local dedup) and appended to Google Sheet

## Files

| File | Purpose |
|------|---------|
| `runner.py` | CLI entrypoint and orchestration |
| `scraper.py` | Greenhouse page scraper |
| `llm.py` | Claude: fit scoring, cover letters, question answering |
| `filler.py` | Playwright form automation |
| `sheets.py` | Google Sheets logging |
| `config.yaml` | Your config (edit this daily) |
| `applied.json` | Auto-maintained local dedup log (gitignored) |
