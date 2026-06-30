"""
filler.py — Playwright automation for Greenhouse application forms.

Standard Greenhouse fields targeted:
  first_name, last_name, email, phone, location
  resume upload
  cover_letter upload (or textarea)
  LinkedIn, GitHub URLs
  custom free-text / select / checkbox questions
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Page, sync_playwright

from scraper import FormField, JobPosting


# Greenhouse field name → config key mapping for well-known fields
_KNOWN_FIELDS: dict[str, tuple[str, ...]] = {
    "first_name":    ("person", "first_name"),
    "last_name":     ("person", "last_name"),
    "email":         ("person", "email"),
    "phone":         ("person", "phone"),
    "location":      ("person", "location"),
    "linkedin_url":  ("person", "linkedin"),
    "website":       ("person", "github"),
    "github":        ("person", "github"),
}


def _person_value(config: dict[str, Any], *keys: str) -> str:
    """Walk config dict by key path, return '' if missing."""
    node: Any = config
    for k in keys:
        if not isinstance(node, dict):
            return ""
        node = node.get(k, "")
    return str(node) if node else ""


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split(maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (full_name, "")


def _fill_text_field(page: Page, name: str, value: str) -> None:
    selectors = [
        f'input[name="{name}"]',
        f'input[id="{name}"]',
        f'textarea[name="{name}"]',
        f'textarea[id="{name}"]',
    ]
    for sel in selectors:
        elem = page.query_selector(sel)
        if elem and elem.is_visible():
            elem.fill(value)
            return


def _fill_select_field(page: Page, name: str, value: str) -> None:
    selectors = [f'select[name="{name}"]', f'select[id="{name}"]']
    for sel in selectors:
        elem = page.query_selector(sel)
        if elem and elem.is_visible():
            try:
                elem.select_option(label=value)
            except Exception:
                try:
                    elem.select_option(value=value)
                except Exception:
                    pass
            return


def _upload_file(page: Page, name: str, file_path: str) -> None:
    selectors = [f'input[type="file"][name="{name}"]', f'input[type="file"][id="{name}"]']
    for sel in selectors:
        elem = page.query_selector(sel)
        if elem:
            elem.set_input_files(file_path)
            return

    # Greenhouse sometimes hides the input; try clicking the upload button first
    upload_btn = page.query_selector(f'[data-source="{name}"] button, label[for="{name}"]')
    if upload_btn:
        upload_btn.click()
        page.wait_for_selector('input[type="file"]:not([disabled])', timeout=5000)
        page.query_selector('input[type="file"]').set_input_files(file_path)


def _cover_letter_as_file(text: str) -> str:
    """Write cover letter text to a temp PDF-like .txt and return the path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="cover_letter_", delete=False
    )
    tmp.write(text)
    tmp.close()
    return tmp.name


def fill_application(
    posting: JobPosting,
    config: dict[str, Any],
    cover_letter_text: Optional[str],
    custom_answers: dict[str, str],
    dry_run: bool = False,
) -> None:
    """
    Open the Greenhouse application page and fill every field.
    If dry_run=True, fills fields but does NOT click the submit button.
    """
    person = config["person"]
    first, last = _split_name(person.get("name", ""))
    resume_path = person.get("resume_pdf", "")

    if not resume_path or not Path(resume_path).exists():
        raise FileNotFoundError(
            f"Resume PDF not found at '{resume_path}'. "
            "Update person.resume_pdf in config.yaml."
        )

    cl_temp_path: Optional[str] = None
    if cover_letter_text:
        cl_temp_path = _cover_letter_as_file(cover_letter_text)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False, slow_mo=80)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(posting.url, wait_until="domcontentloaded", timeout=30_000)

            # ── Standard known fields ──────────────────────────────────────────
            _fill_text_field(page, "first_name", first)
            _fill_text_field(page, "last_name", last)
            _fill_text_field(page, "email", person.get("email", ""))
            _fill_text_field(page, "phone", person.get("phone", ""))

            # Location autocomplete — type and wait for suggestion
            loc_input = page.query_selector('input[name="location"], input[id="location"]')
            if loc_input and loc_input.is_visible():
                loc_input.fill(person.get("location", ""))
                page.wait_for_timeout(1500)
                suggestion = page.query_selector('ul[role="listbox"] li, .pac-item')
                if suggestion:
                    suggestion.click()

            _fill_text_field(page, "linkedin_url", person.get("linkedin", ""))
            _fill_text_field(page, "website", person.get("github", ""))

            # ── Resume upload ──────────────────────────────────────────────────
            _upload_file(page, "resume", resume_path)

            # ── Cover letter ───────────────────────────────────────────────────
            if cover_letter_text:
                # Try textarea first (some Greenhouse forms embed a textarea)
                cl_textarea = page.query_selector(
                    'textarea[name*="cover"], textarea[id*="cover"]'
                )
                if cl_textarea and cl_textarea.is_visible():
                    cl_textarea.fill(cover_letter_text)
                else:
                    # Fall back to file upload
                    _upload_file(page, "cover_letter", cl_temp_path)  # type: ignore[arg-type]

            # ── Custom questions ───────────────────────────────────────────────
            for form_field in posting.form_fields:
                answer = custom_answers.get(form_field.label)
                if not answer:
                    continue

                if form_field.field_type in ("text", "textarea"):
                    _fill_text_field(page, form_field.name, answer)
                elif form_field.field_type == "select":
                    _fill_select_field(page, form_field.name, answer)

            # ── Submit ─────────────────────────────────────────────────────────
            if not dry_run:
                submit_btn = page.query_selector(
                    'button[type="submit"], input[type="submit"]'
                )
                if submit_btn:
                    submit_btn.click()
                    page.wait_for_load_state("networkidle", timeout=15_000)
                else:
                    raise RuntimeError("Submit button not found on Greenhouse page.")
            else:
                # Pause so you can inspect what was filled
                page.wait_for_timeout(5000)

            browser.close()
    finally:
        if cl_temp_path and Path(cl_temp_path).exists():
            os.unlink(cl_temp_path)
