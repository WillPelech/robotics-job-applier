"""
scraper.py — fetch and parse a Greenhouse job posting page.

Greenhouse job pages are behind AWS WAF and use JS-rendered forms (Selectize
widgets), so we use Playwright for everything:
  - page fetch (bypasses WAF / follows custom-domain redirects)
  - form field extraction (via JS evaluation, avoids Selectize serialization issues)
  - static content (title, location, description) via BeautifulSoup on the live DOM

Returns a JobPosting dataclass with:
  - title, company, location, description (plain text)
  - form_fields: list of FormField with label, type, name, required, options
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright


@dataclass
class FormField:
    label: str
    field_type: str        # "text" | "textarea" | "select" | "file" | "checkbox"
    name: str              # stable snake_case name derived from label
    required: bool
    options: list[str] = field(default_factory=list)  # for select fields


@dataclass
class JobPosting:
    url: str
    title: str
    company: str
    location: str
    description: str
    form_fields: list[FormField]


# Regex to identify standard fields that don't need LLM answers
STANDARD_FIELD_LABELS = re.compile(
    r"first name|last name|email|phone|location|resume|cover letter"
    r"|linkedin|website|github|portfolio",
    re.I,
)

_REQUIRED_RE = re.compile(r"\(required\)", re.I)


def _clean_text(soup_elem) -> str:
    if soup_elem is None:
        return ""
    return re.sub(r"\s+", " ", soup_elem.get_text(separator=" ")).strip()


def _label_to_name(label: str) -> str:
    """Convert a human label to a stable snake_case identifier."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


_EXTRACT_FIELDS_JS = """() => {
    const labels = Array.from(document.querySelectorAll('label[for]'));
    const seen = new Set();
    const results = [];

    for (const lbl of labels) {
        const forId = lbl.getAttribute('for');
        if (!forId || seen.has(forId)) continue;
        seen.add(forId);

        const target = document.getElementById(forId);
        if (!target) continue;
        if (target.type === 'hidden') continue;

        const tagName = target.tagName.toLowerCase();
        const inputType = (target.type || tagName).toLowerCase();

        // Collect select options
        let options = [];
        if (tagName === 'select') {
            options = Array.from(target.options)
                .filter(o => o.value)
                .map(o => o.text.trim());
        }

        results.push({
            label: lbl.innerText.trim(),
            forId: forId,
            tagName: tagName,
            inputType: inputType,
            name: target.name || null,
            options: options,
        });
    }
    return results;
}"""

_EXTRACT_META_JS = """() => ({
    title: (
        document.querySelector('h3.job-title')
        || document.querySelector('[class*="job-title"]')
        || document.querySelector('h1')
        || {}
    ).innerText || '',
    location: (
        document.querySelector('li.job-component-location')
        || document.querySelector('[class*="job-location"]')
        || {}
    ).innerText || '',
    description: (
        document.querySelector('#content')
        || document.querySelector('[class*="job-description"]')
        || document.querySelector('[class*="description"]')
        || document.body
        || {}
    ).innerText || '',
    ogSiteName: (document.querySelector('meta[property="og:site_name"]') || {}).content || '',
    pageTitle: document.title || '',
})"""


def _parse_fields(raw_fields: list[dict[str, Any]]) -> list[FormField]:
    fields: list[FormField] = []
    seen_names: set[str] = set()

    for f in raw_fields:
        raw_label = f.get("label", "")
        required = bool(_REQUIRED_RE.search(raw_label))
        label = _REQUIRED_RE.sub("", raw_label).strip()

        tag = f.get("tagName", "input")
        itype = f.get("inputType", "text")

        if itype == "file":
            ftype = "file"
        elif itype == "checkbox":
            ftype = "checkbox"
        elif tag == "textarea":
            ftype = "textarea"
        elif tag == "select" or itype == "select-one":
            ftype = "select"
        elif itype == "hidden":
            continue
        else:
            ftype = "text"

        name = _label_to_name(label)
        if not name or name in seen_names:
            continue
        seen_names.add(name)

        fields.append(FormField(
            label=label,
            field_type=ftype,
            name=name,
            required=required,
            options=f.get("options", []),
        ))

    return fields


def scrape_greenhouse(url: str, timeout_ms: int = 25_000) -> JobPosting:
    """Fetch a Greenhouse job page via Playwright and return a structured JobPosting."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        # Wait for application form labels to appear
        try:
            page.wait_for_selector("label[for]", timeout=12_000)
        except Exception:
            pass

        meta: dict[str, str] = page.evaluate(_EXTRACT_META_JS)
        raw_fields: list[dict] = page.evaluate(_EXTRACT_FIELDS_JS)
        browser.close()

    # Resolve company name
    company = meta.get("ogSiteName", "").strip()
    if not company:
        page_title = meta.get("pageTitle", "")
        parts = page_title.split(" at ")
        if len(parts) >= 2:
            company = parts[-1].strip().rstrip(" |").strip()

    description = re.sub(r"\s+", " ", meta.get("description", "")).strip()
    title = meta.get("title", "").strip()
    location = meta.get("location", "").strip()

    return JobPosting(
        url=url,
        title=title,
        company=company,
        location=location,
        description=description,
        form_fields=_parse_fields(raw_fields),
    )
