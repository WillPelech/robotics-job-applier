# Robotics Job Auto-Applier

A daily CLI tool that reads a config of personal info and Greenhouse job posting URLs, uses Claude to score fit and draft cover letters, then auto-fills and submits applications via Playwright.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # add ANTHROPIC_API_KEY
```

## Configuration

Edit `config.yaml`:

- `person:` — your name, email, phone, location, LinkedIn, GitHub, resume PDF path, and a free-form background bio
- `roles:` — job titles and skill keywords used for fit scoring
- `allowlist:` — Greenhouse posting URLs to process today
- `cover_letter:` — `auto` (only when required) | `never` | `always`
- `fit_threshold:` — minimum Claude fit score (0–10) to attempt an application

## Daily Usage

```bash
# Add URLs to allowlist in config.yaml, then:
python runner.py --dry-run   # fill forms but don't submit (for inspection)
python runner.py             # submit all new jobs in the allowlist
python runner.py --url https://boards.greenhouse.io/company/jobs/123  # single URL
```

## How It Works

1. For each URL in `allowlist` not already in `applied.json`:
   - Scrapes the Greenhouse job page (title, description, form fields)
   - Claude scores fit against your `roles` and `background` (skips if below `fit_threshold`)
   - Playwright fills standard fields (name, email, phone, location, resume)
   - If the cover letter field is required (and `cover_letter != never`), Claude writes one
   - Claude answers any custom free-text questions using your background
   - Submits the form (or pauses for 5s in `--dry-run` mode)
2. Result recorded in `applied.json` — duplicates are skipped on future runs

## Files

| File | Purpose |
|------|---------|
| `runner.py` | CLI entrypoint and orchestration |
| `scraper.py` | Greenhouse page scraper |
| `llm.py` | Claude: fit scoring, cover letters, question answering |
| `filler.py` | Playwright form automation |
| `config.yaml` | Your config (edit this daily) |
| `applied.json` | Auto-maintained log of processed jobs (gitignored) |
