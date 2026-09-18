"""Wires dictionaries/seniority_parsing.yml into the combined postings
table. One row per posting. Two independent signals kept as separate
columns, never collapsed — the mismatch between them (a "junior" title
secretly requiring 3+ years) is the actual finding for question 5, and
blending them here would make that comparison impossible downstream.

Logic ported unchanged from the validated dry-run: unit word is mandatory
in the "minimum/at least N ___" pattern (an earlier draft made it optional
and matched "at least 3 months" as if it said years), implausible numbers
(>20 years) are rejected outright, and company/agency "About us" boilerplate
citing their own tenure is masked before extraction.

Recall limit: Adzuna's description is capped at 500 chars, so an experience
clause appearing later in the real posting is invisible here for Adzuna rows
specifically — many "Senior"-titled postings will show years_experience as
null not because none was stated, but because the snippet doesn't reach it.
EURES rows (uncapped text) don't have this limit.
"""

import re
from pathlib import Path

import pandas as pd
import yaml

SENIORITY_PATH = Path("../dictionaries/seniority_parsing.yml")


def mask_exclusions(text, patterns):
    for pat in patterns:
        text = re.sub(pat, "XXXX", text, flags=re.IGNORECASE)
    return text


def extract_years(text, spec):
    masked = mask_exclusions(text, spec["experience_context_exclusions"])
    for pat in spec["years_experience_patterns"]:
        m = re.search(pat, masked, re.IGNORECASE)
        if m:
            nums = [int(g) for g in m.groups() if g and g.isdigit()]
            if not nums:
                continue
            lo, hi = min(nums), max(nums)
            if lo > spec["max_plausible_years"] or hi > spec["max_plausible_years"]:
                continue
            return lo, (hi if hi != lo else None)
    for pat in spec["entry_level_phrases"]:
        if re.search(pat, masked, re.IGNORECASE):
            return 0, 0
    return None, None


def classify_title_seniority(title, spec):
    if not title:
        return "unspecified"
    for level in ("junior", "senior", "mid"):
        for pat in spec["title_seniority_markers"].get(level, []):
            if re.search(pat, title, re.IGNORECASE):
                return level
    return "unspecified"


def model(dbt, session):
    postings = dbt.ref("int_postings_deduped").df()
    with open(SENIORITY_PATH, encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    rows = []
    for row in postings.itertuples():
        years_min, years_max = extract_years(row.description_text or "", spec)
        rows.append({
            "source_posting_key": row.source_posting_key,
            "posting_id": row.posting_id,
            "snapshot_date": row.snapshot_date,
            "source_system": row.source_system,
            "country_code": row.country_code,
            "years_experience_min": years_min,
            "years_experience_max": years_max,
            "title_seniority": classify_title_seniority(row.job_title, spec),
        })

    return pd.DataFrame(rows)
