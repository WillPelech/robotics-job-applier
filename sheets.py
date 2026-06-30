"""
sheets.py — append job application records to a Google Sheet.

Setup: see README.md § Google Sheets Setup.

The sheet is expected to have this header row (created automatically if the
sheet is empty):
  Date | Title | Company | Location | URL | Status | Fit Score | Reason
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_gc: gspread.Client | None = None
_sheet: gspread.Worksheet | None = None

HEADER = ["Date", "Title", "Company", "Location", "URL", "Status", "Fit Score", "Reason"]


def _get_sheet(spreadsheet_id: str, worksheet_name: str = "Applications") -> gspread.Worksheet:
    global _gc, _sheet
    if _sheet is not None:
        return _sheet

    creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not set. "
            "See README.md § Google Sheets Setup."
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    _gc = gspread.authorize(creds)

    spreadsheet = _gc.open_by_key(spreadsheet_id)

    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=len(HEADER))

    # Write header if sheet is empty
    if ws.row_count == 0 or not ws.row_values(1):
        ws.append_row(HEADER, value_input_option="RAW")

    _sheet = ws
    return ws


def log_application(
    spreadsheet_id: str,
    title: str,
    company: str,
    location: str,
    url: str,
    status: str,
    fit_score: int | None = None,
    reason: str = "",
    worksheet_name: str = "Applications",
) -> None:
    """Append one row to the tracking sheet. Silently skips if sheet is not configured."""
    if not spreadsheet_id:
        return

    ws = _get_sheet(spreadsheet_id, worksheet_name)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    score_str = str(fit_score) if fit_score is not None else ""

    ws.append_row(
        [date_str, title, company, location, url, status, score_str, reason],
        value_input_option="USER_ENTERED",
    )
