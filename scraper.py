"""
scraper.py — fetch and parse a Greenhouse job posting page.

Returns a JobPosting dataclass with:
  - title, company, location, description (plain text)
  - form_fields: list of FormField describing what the application form asks for
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup


@dataclass
class FormField:
    label: str
    field_type: str        # "text" | "textarea" | "select" | "file" | "checkbox"
    name: str              # HTML name/id attribute
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


def _clean_text(soup_elem) -> str:
    if soup_elem is None:
        return ""
    return re.sub(r"\s+", " ", soup_elem.get_text(separator=" ")).strip()


def _parse_form_fields(soup: BeautifulSoup) -> list[FormField]:
    fields: list[FormField] = []

    # Greenhouse wraps each question in a div.field or li.field
    question_containers = soup.select("li.field, div.field")

    for container in question_containers:
        label_elem = container.find("label")
        if not label_elem:
            continue

        label_text = _clean_text(label_elem)
        required = bool(container.select_one("abbr[title='required'], span.required"))

        inp = container.find("input")
        textarea = container.find("textarea")
        select = container.find("select")

        if inp:
            input_type = inp.get("type", "text").lower()
            if input_type == "file":
                ftype = "file"
            elif input_type == "checkbox":
                ftype = "checkbox"
            else:
                ftype = "text"
            fname = inp.get("name") or inp.get("id") or label_text.lower().replace(" ", "_")
            fields.append(FormField(label=label_text, field_type=ftype, name=fname, required=required))

        elif textarea:
            fname = textarea.get("name") or textarea.get("id") or label_text.lower().replace(" ", "_")
            fields.append(FormField(label=label_text, field_type="textarea", name=fname, required=required))

        elif select:
            fname = select.get("name") or select.get("id") or label_text.lower().replace(" ", "_")
            options = [o.get_text(strip=True) for o in select.find_all("option") if o.get("value")]
            fields.append(FormField(label=label_text, field_type="select", name=fname, required=required, options=options))

    # Deduplicate by name while preserving order
    seen: set[str] = set()
    unique: list[FormField] = []
    for f in fields:
        if f.name not in seen:
            seen.add(f.name)
            unique.append(f)
    return unique


def scrape_greenhouse(url: str, timeout: int = 15) -> JobPosting:
    """Fetch a Greenhouse job page and return a structured JobPosting."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title
    title_elem = (
        soup.find("h1", class_=re.compile(r"app-title|posting-headline"))
        or soup.find("h1")
    )
    title = _clean_text(title_elem)

    # Company — Greenhouse embeds it in the page header or <title>
    company = ""
    meta_company = soup.find("meta", {"property": "og:site_name"})
    if meta_company:
        company = meta_company.get("content", "").strip()
    if not company:
        page_title = soup.find("title")
        if page_title:
            parts = page_title.get_text().split(" at ")
            if len(parts) >= 2:
                company = parts[-1].strip().rstrip(" |").strip()

    # Location
    location_elem = soup.find(class_=re.compile(r"location|job-location"))
    location = _clean_text(location_elem)

    # Description — the main content section
    desc_elem = (
        soup.find("div", id="content")
        or soup.find("div", class_=re.compile(r"job-description|content"))
    )
    description = _clean_text(desc_elem) if desc_elem else _clean_text(soup.find("body"))

    form_fields = _parse_form_fields(soup)

    return JobPosting(
        url=url,
        title=title,
        company=company,
        location=location,
        description=description,
        form_fields=form_fields,
    )
