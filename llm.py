"""
llm.py — Claude-powered helpers:
  - score_fit:        rate how well a job matches the candidate (0–10)
  - write_cover_letter: generate a concise, tailored cover letter
  - answer_question:  answer a single free-text application question
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


_FAST_MODEL = "claude-haiku-3-5"   # fit scoring — cheap, fast
_STRONG_MODEL = "claude-opus-4-5"  # cover letters + Q&A — higher quality


def _chat(system: str, user: str, max_tokens: int = 1024, model: str = _STRONG_MODEL) -> str:
    client = _get_client()
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


# ─── Fit Scoring ──────────────────────────────────────────────────────────────

_FIT_SYSTEM = """\
You are a ruthlessly honest career advisor. Given a job description and a
candidate profile, output ONLY valid JSON with two keys:
  "score": integer 0–10  (10 = perfect match)
  "reason": one sentence explaining the score

Do not output anything else — no markdown fences, no prose.\
"""


def score_fit(job_title: str, job_description: str, person: dict[str, Any], roles: list[str]) -> tuple[int, str]:
    """
    Returns (score, reason).
    score is 0–10; reason is a one-sentence explanation.
    """
    user_prompt = f"""
JOB TITLE: {job_title}

JOB DESCRIPTION:
{job_description[:4000]}

CANDIDATE PROFILE:
Name: {person['name']}
Years of experience: {person.get('years_experience', 'unknown')}
Role interests / skills: {', '.join(roles)}
Background:
{person.get('background', '')}
"""
    raw = _chat(_FIT_SYSTEM, user_prompt, max_tokens=256, model=_FAST_MODEL)

    # Tolerate minor JSON wrapping from the model
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        data = json.loads(raw)
        return int(data["score"]), str(data["reason"])
    except Exception:
        # Fallback: try to extract a bare integer from the text
        m = re.search(r"\b([0-9]|10)\b", raw)
        score = int(m.group(1)) if m else 5
        return score, raw[:200]


# ─── Cover Letter ─────────────────────────────────────────────────────────────

_CL_SYSTEM = """\
You are an expert at writing concise, authentic cover letters for engineering roles.
Write a cover letter that:
- Is addressed to the hiring team (no specific name)
- Opens with genuine enthusiasm for the specific role and company
- Highlights 2–3 directly relevant experiences from the candidate's background
- Closes with a confident, brief call to action
- Is 3–4 short paragraphs, under 300 words
- Avoids clichés ("I am writing to apply…", "passionate", "leverage", "synergy")
- Reads like a human wrote it, not a template

Output only the cover letter text, no subject line or date.\
"""


def write_cover_letter(job_title: str, company: str, job_description: str, person: dict[str, Any]) -> str:
    user_prompt = f"""
ROLE: {job_title} at {company}

JOB DESCRIPTION (excerpt):
{job_description[:3000]}

CANDIDATE BACKGROUND:
{person.get('background', '')}
"""
    return _chat(_CL_SYSTEM, user_prompt, max_tokens=600)


# ─── Custom Question Answering ─────────────────────────────────────────────────

_QA_SYSTEM = """\
You are helping a job applicant answer a specific question on an application form.
Write a concise, honest answer using only the candidate information provided.
Aim for 2–4 sentences unless the question clearly warrants more.
Output only the answer text — no preamble, no quotes around the answer.\
"""


def answer_question(question: str, job_title: str, company: str, person: dict[str, Any]) -> str:
    user_prompt = f"""
QUESTION: {question}

ROLE BEING APPLIED TO: {job_title} at {company}

CANDIDATE INFORMATION:
Name: {person['name']}
Background:
{person.get('background', '')}
"""
    return _chat(_QA_SYSTEM, user_prompt, max_tokens=400)
