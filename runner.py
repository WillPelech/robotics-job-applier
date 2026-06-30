#!/usr/bin/env python3
"""
runner.py — daily entrypoint for the Robotics Job Auto-Applier.

Usage:
    python runner.py              # run all jobs in config.yaml allowlist
    python runner.py --dry-run    # fill forms but do not submit
    python runner.py --url URL    # process a single URL (ignores allowlist)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from filler import fill_application
from llm import answer_question, score_fit, write_cover_letter
from scraper import FormField, scrape_greenhouse

APPLIED_PATH = Path(__file__).parent / "applied.json"
CONFIG_PATH = Path(__file__).parent / "config.yaml"


# ─── Persistence ──────────────────────────────────────────────────────────────

def _load_applied() -> list[dict[str, Any]]:
    if APPLIED_PATH.exists():
        with open(APPLIED_PATH) as f:
            return json.load(f)
    return []


def _save_applied(records: list[dict[str, Any]]) -> None:
    with open(APPLIED_PATH, "w") as f:
        json.dump(records, f, indent=2)


def _already_applied(records: list[dict[str, Any]], url: str) -> bool:
    return any(r["url"] == url for r in records)


def _record(
    records: list[dict[str, Any]],
    url: str,
    status: str,
    title: str = "",
    company: str = "",
    reason: str = "",
) -> None:
    records.append(
        {
            "url": url,
            "title": title,
            "company": company,
            "status": status,       # "applied" | "skipped_low_fit" | "error" | "dry_run"
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_applied(records)


# ─── Core per-job logic ───────────────────────────────────────────────────────

def _is_cover_letter_field(field: FormField) -> bool:
    return "cover" in field.label.lower() or "cover" in field.name.lower()


def _is_standard_field(field: FormField) -> bool:
    standard_names = {
        "first_name", "last_name", "email", "phone", "location",
        "resume", "cover_letter", "linkedin_url", "website", "github",
    }
    return field.name in standard_names or _is_cover_letter_field(field)


def process_job(
    url: str,
    config: dict[str, Any],
    applied_records: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    person = config["person"]
    roles: list[str] = config.get("roles", [])
    fit_threshold: int = int(config.get("fit_threshold", 7))
    cl_mode: str = config.get("cover_letter", "auto")

    print(f"\n{'='*60}")
    print(f"Processing: {url}")

    # ── Scrape ─────────────────────────────────────────────────────────────────
    try:
        posting = scrape_greenhouse(url)
    except Exception as exc:
        print(f"  [ERROR] Failed to scrape: {exc}")
        _record(applied_records, url, "error", reason=str(exc))
        return

    print(f"  Title:   {posting.title}")
    print(f"  Company: {posting.company}")
    print(f"  Fields:  {len(posting.form_fields)} detected")

    # ── Fit check ──────────────────────────────────────────────────────────────
    score, reason = score_fit(posting.title, posting.description, person, roles)
    print(f"  Fit score: {score}/10 — {reason}")

    if score < fit_threshold:
        print(f"  [SKIP] Score {score} < threshold {fit_threshold}.")
        _record(
            applied_records, url, "skipped_low_fit",
            title=posting.title, company=posting.company,
            reason=f"Score {score}: {reason}",
        )
        return

    # ── Cover letter decision ──────────────────────────────────────────────────
    cl_fields = [f for f in posting.form_fields if _is_cover_letter_field(f)]
    cl_required = any(f.required for f in cl_fields)
    cl_present = bool(cl_fields)

    cover_letter_text: str | None = None
    if cl_mode == "never":
        pass
    elif cl_mode == "always":
        print("  Generating cover letter (always mode)…")
        cover_letter_text = write_cover_letter(posting.title, posting.company, posting.description, person)
    elif cl_mode == "auto":
        if cl_required:
            print("  Generating cover letter (field required)…")
            cover_letter_text = write_cover_letter(posting.title, posting.company, posting.description, person)
        elif cl_present:
            print("  Cover letter field is optional — skipping (auto mode).")

    # ── Custom question answers ────────────────────────────────────────────────
    custom_fields = [f for f in posting.form_fields if not _is_standard_field(f)]
    custom_answers: dict[str, str] = {}

    for field in custom_fields:
        if field.field_type in ("text", "textarea"):
            print(f"  Answering: "{field.label}"…")
            custom_answers[field.label] = answer_question(
                field.label, posting.title, posting.company, person
            )
        elif field.field_type == "select" and field.options:
            # Pick the first option as a safe default; the user can override
            custom_answers[field.label] = field.options[0]

    # ── Fill & submit ──────────────────────────────────────────────────────────
    action = "dry-run filling" if dry_run else "submitting"
    print(f"  {action.capitalize()} application…")
    try:
        fill_application(posting, config, cover_letter_text, custom_answers, dry_run=dry_run)
    except Exception as exc:
        print(f"  [ERROR] Form filling failed: {exc}")
        _record(applied_records, url, "error", title=posting.title, company=posting.company, reason=str(exc))
        return

    status = "dry_run" if dry_run else "applied"
    print(f"  [OK] Status: {status}")
    _record(applied_records, url, status, title=posting.title, company=posting.company)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Robotics Job Auto-Applier")
    parser.add_argument("--dry-run", action="store_true", help="Fill forms but do not submit")
    parser.add_argument("--url", metavar="URL", help="Process a single URL instead of the allowlist")
    parser.add_argument(
        "--config", metavar="PATH", default=str(CONFIG_PATH),
        help="Path to config.yaml (default: config.yaml next to runner.py)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    applied_records = _load_applied()

    urls: list[str] = [args.url] if args.url else config.get("allowlist", [])
    if not urls:
        print("No URLs to process. Add entries to 'allowlist' in config.yaml.")
        return

    print(f"Jobs to process: {len(urls)}")
    print(f"Dry run: {args.dry_run}")

    skipped_already = 0
    for url in urls:
        if _already_applied(applied_records, url):
            print(f"\n[SKIP] Already processed: {url}")
            skipped_already += 1
            continue
        process_job(url, config, applied_records, dry_run=args.dry_run)

    applied_count = sum(1 for r in applied_records if r["status"] == "applied")
    print(f"\n{'='*60}")
    print(f"Done. Applied: {applied_count}  |  Skipped (duplicate): {skipped_already}")


if __name__ == "__main__":
    main()
