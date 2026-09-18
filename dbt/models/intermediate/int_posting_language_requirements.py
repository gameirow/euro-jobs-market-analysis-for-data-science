"""Wires dictionaries/language_requirements.yml into the combined postings
table. One row per (posting, language) — 3 rows per posting always (english/
german/french), requirement_level in {required, preferred, mentioned, none}.
Logic ported unchanged from the validated dry-run (see conversation): tier
check order is preferred -> required -> mention (preferred must win over the
broad "bare Xkenntnisse defaults to required" rule), exclusions masked first,
compound-noun expansion applied before matching.

Recall limit: Adzuna's description is capped at 500 chars, so a language
clause appearing later in the real posting is invisible here for Adzuna rows
specifically. EURES rows (uncapped text) don't have this limit.
"""

import re
from pathlib import Path

import pandas as pd
import yaml

LANG_DICT_PATH = Path("../dictionaries/language_requirements.yml")


def expand_shared_suffix_compounds(text):
    def repl(m):
        first, conj, second, suffix = m.group(1), m.group(2), m.group(4), m.group(5)
        return f"{first}{suffix} {conj} {second}{suffix}"
    return re.sub(
        r"(\w+)-\s*(und|and|et)\s*(\w+\s+)?(\w+)(kenntnisse|sprachige?[nr]?)",
        repl, text, flags=re.IGNORECASE,
    )


def mask_exclusions(text, exclusion_patterns):
    for pat in exclusion_patterns:
        text = re.sub(pat, "XXXX", text, flags=re.IGNORECASE)
    return text


TIER_LABELS = {
    "preferred_patterns": "preferred",
    "required_patterns": "required",
    "mention_patterns": "mentioned",
}


def classify(text, lang_spec):
    masked = mask_exclusions(text, lang_spec.get("exclusion_patterns", []))
    for tier in ("preferred_patterns", "required_patterns", "mention_patterns"):
        for pat in lang_spec.get(tier, []):
            if re.search(pat, masked, re.IGNORECASE):
                return TIER_LABELS[tier]
    return "none"


def model(dbt, session):
    postings = dbt.ref("int_postings_deduped").df()
    with open(LANG_DICT_PATH, encoding="utf-8") as f:
        lang_dict = yaml.safe_load(f)["languages"]

    rows = []
    for row in postings.itertuples():
        text = expand_shared_suffix_compounds(f"{row.job_title or ''} {row.description_text or ''}")
        for lang, spec in lang_dict.items():
            rows.append({
                "posting_language_key": f"{row.source_posting_key}|{lang}",
                "source_posting_key": row.source_posting_key,
                "posting_id": row.posting_id,
                "snapshot_date": row.snapshot_date,
                "source_system": row.source_system,
                "country_code": row.country_code,
                "language": lang,
                "requirement_level": classify(text, spec),
            })

    return pd.DataFrame(rows)
