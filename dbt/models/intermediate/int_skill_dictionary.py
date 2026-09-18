"""Parses dictionaries/skill_dictionary.yml into one row per
(category, skill_key), with a fully compiled regex `pattern` ready for
DuckDB's regexp_matches (RE2 syntax; matched case-insensitively via the 'i'
option downstream, not baked into the pattern string).

Path is relative to the dbt invocation's working directory (this project's
convention is to always run dbt from dbt/, the same assumption already relied
on by sources.yml's external_location paths).
"""

import re
from pathlib import Path

import pandas as pd
import yaml

DICTIONARY_PATH = Path("../dictionaries/skill_dictionary.yml")


def build_pattern(category_skills, skill_key, spec):
    match_mode = spec.get("match_mode", "default")
    own_alt = "|".join(re.escape(v) for v in spec["variants"])

    if match_mode == "default":
        return rf"\b(?:{own_alt})\b"

    if match_mode == "list_context":
        # Only count a match when it sits next to another language from the
        # same category via a comma or slash, e.g. "(Python, R, SQL)" or
        # "Python/R" — validated against real postings before this rule was
        # adopted (see the skill's `note` in the dictionary YAML).
        other_variants = [
            v
            for other_key, other_spec in category_skills.items()
            if other_key != skill_key
            and other_spec.get("match_mode", "default") != "list_context"
            for v in other_spec["variants"]
        ]
        other_alt = "|".join(re.escape(v) for v in other_variants)
        return (
            rf"(?:{other_alt})\s*(?:,|/)\s*(?:{own_alt})\b"
            rf"|\b(?:{own_alt})\s*(?:,|/)\s*(?:{other_alt})\b"
        )

    raise ValueError(f"Unknown match_mode {match_mode!r} for skill {skill_key!r}")


def model(dbt, session):
    with open(DICTIONARY_PATH, encoding="utf-8") as f:
        skill_dict = yaml.safe_load(f)["categories"]

    rows = []
    for category, skills in skill_dict.items():
        for skill_key, spec in skills.items():
            rows.append(
                {
                    "category": category,
                    "skill_key": skill_key,
                    "match_mode": spec.get("match_mode", "default"),
                    "variant_count": len(spec["variants"]),
                    "pattern": build_pattern(skills, skill_key, spec),
                }
            )

    return pd.DataFrame(rows)
