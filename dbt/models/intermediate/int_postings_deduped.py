"""Cross-source dedup: links Adzuna and EURES rows that are almost certainly
the same real-world posting, without merging them into one row (link, don't
merge — see conversation for why: picking a "winner" per field would throw
away data, and hides the uncertainty that's inherent to fuzzy matching).

Approach (proposed and confirmed before building):
  1. Block candidate pairs to adzuna x eures within the same country_code and
     within POSTED_AT_WINDOW_DAYS of each other's posted_at. Only cross-source
     pairs are considered — same-source duplicates are a different problem,
     out of scope here.
  2. Normalize company name (country-aware legal-suffix stripping — GmbH/AG
     for DE/CH/AT, SARL/SAS for FR, S.r.l./S.p.A. for IT, B.V./N.V. for NL,
     Sp. z o.o. for PL, Lda. for PT, ApS/A/S for DK, S.L./S.A. for ES) and job
     title (strip gender markers like "(m/w/d)" everywhere; additionally
     strip EURES's trailing ESCO occupation-label parenthetical, e.g.
     "... (Data Scientist)" — an EURES-only convention, so only stripped for
     eures rows, or it would wrongly eat real content like "Analyst (Remote)"
     from an Adzuna title).
  3. Resolve location: EURES gives NUTS codes (no shared vocabulary with
     Adzuna's human-readable text), so this does NOT compare codes directly —
     it resolves each EURES posting's NUTS code to a place NAME via
     int_nuts_lookup, then fuzzy-compares that name against Adzuna's location
     text. Adzuna never has NUTS codes at all, so code-to-code comparison is
     not possible in principle, not just unimplemented.
  4. Score each blocked pair on company/title/location similarity
     (rapidfuzz), weighted average over whichever signals are actually
     available (missing location isn't evidence of a non-match, so it's
     excluded from the average rather than scored as 0).
  5. Greedy one-to-one assignment: highest-scoring pair above THRESHOLD wins,
     both postings removed from the pool, repeat.

Output: every row from int_postings_all_sources, unchanged, plus
dedup_group_id (shared by a matched pair, otherwise the row's own key) and
dedup_score (null for unmatched rows) — and the normalized company name,
which is what question 4's employer rankings should group on instead of raw
company_name (so "Google" / "Google Inc." / "Google Switzerland GmbH" collapse
to one employer without a separate normalization pass).

THRESHOLD below is provisional — see the conversation for the boundary-case
sample used to sanity-check it before trusting it.
"""

import re

import pandas as pd
from rapidfuzz import fuzz

POSTED_AT_WINDOW_DAYS = 5
THRESHOLD = 0.78

COUNTRY_COMPANY_SUFFIXES = {
    "de": [r"gmbh\s*&\s*co\.?\s*kg", r"gmbh", r"\bag\b", r"\bmbh\b", r"\be\.?v\.?\b", r"\bug\b"],
    "at": [r"gmbh\s*&\s*co\.?\s*kg", r"gmbh", r"\bag\b"],
    "ch": [r"\bag\b", r"gmbh", r"\bsa\b", r"s\.?a\.?r\.?l\.?", r"\bsagl\b"],
    "fr": [r"\bsarl\b", r"\bsasu\b", r"\bsas\b", r"\bsa\b", r"\beurl\b"],
    "it": [r"s\.?r\.?l\.?", r"s\.?p\.?a\.?", r"s\.?a\.?s\.?", r"s\.?n\.?c\.?"],
    "nl": [r"b\.?v\.?", r"n\.?v\.?"],
    "pl": [r"sp\.?\s*z\s*o\.?o\.?", r"\bsa\b", r"sp\.?k\.?"],
    "pt": [r"\blda\.?\b", r"\bsa\b", r"unipessoal"],
    "dk": [r"\baps\b", r"a/s"],
    "es": [r"s\.?l\.?u?\.?", r"\bsa\b"],
}
GENERIC_COMPANY_SUFFIXES = [r"\bltd\.?\b", r"\binc\.?\b", r"\bcorp\.?\b", r"\bgroup\b", r"\bholding\b"]

GENDER_MARKER_PATTERN = re.compile(r"\(\s*[mwfhdx](?:\s*/\s*[mwfhdx]){1,3}\s*\)", re.IGNORECASE)
TRAILING_PAREN_PATTERN = re.compile(r"\([^()]*\)\s*$")


# Not real employer names — scraping/markup artifacts observed in Adzuna's
# company_name field during boundary sampling (2026-09-18). "jobposting" is
# literally the Schema.org structured-data type name leaking through. Treated
# as missing (excluded from scoring) rather than a real distinct company,
# since counting it as a mismatch was suppressing genuine duplicates whose
# real company only appeared on the EURES side.
KNOWN_PLACEHOLDER_COMPANY_NAMES = {"jobposting"}


def normalize_company(name, country_code):
    if not name:
        return ""
    text = str(name).lower()
    for pattern in COUNTRY_COMPANY_SUFFIXES.get(country_code, []) + GENERIC_COMPANY_SUFFIXES:
        text = re.sub(pattern, " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text in KNOWN_PLACEHOLDER_COMPANY_NAMES else text


def normalize_title(title, source_system):
    if not title:
        return ""
    text = GENDER_MARKER_PATTERN.sub(" ", str(title))
    if source_system == "eures":
        text = TRAILING_PAREN_PATTERN.sub("", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_eures_location(nuts_codes, nuts_lookup_by_id):
    if not nuts_codes:
        return None
    first_code = str(nuts_codes).split("|")[0]
    return nuts_lookup_by_id.get(first_code)


def normalize_location(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def shares_a_role(a, b):
    """Hard gate: never consider two postings a match unless they were found
    via at least one shared search phrase (data scientist / data analyst /
    business intelligence). Without this, a staffing agency's "Data Analyst"
    listing and its unrelated "Data Scientist GenAI" listing get compared at
    all — company-name and boilerplate-title similarity alone can't tell
    those apart (verified: this was producing real false positives at any
    threshold below ~0.85 before this gate was added)."""
    a_roles = set((a.matched_role_queries or "").split("|"))
    b_roles = set((b.matched_role_queries or "").split("|"))
    return bool(a_roles & b_roles)


def pair_score(a, b):
    """a, b are namedtuples from DataFrame.itertuples()."""
    signals = []

    # Empty-vs-empty (e.g. company_name missing on both sides) must NOT
    # count as a match — that inflated scores for genuinely unrelated
    # postings that simply both lacked a company name.
    if a.company_norm and b.company_norm:
        signals.append((fuzz.token_sort_ratio(a.company_norm, b.company_norm) / 100, 0.25))

    if a.title_norm and b.title_norm:
        signals.append((fuzz.token_sort_ratio(a.title_norm, b.title_norm) / 100, 0.25))

    if a.location_norm and b.location_norm:
        signals.append((fuzz.partial_ratio(a.location_norm, b.location_norm) / 100, 0.15))

    # Weighted most heavily: a genuine cross-source duplicate is the same
    # underlying ad text, which is far more discriminating than company/title
    # for telling "the same posting, syndicated twice" apart from "two
    # different postings that happen to look similar" (e.g. a staffing
    # agency's near-identical template across different real vacancies).
    if a.description_text and b.description_text:
        signals.append((fuzz.partial_ratio(a.description_text, b.description_text) / 100, 0.35))

    if not signals:
        return 0.0

    total_weight = sum(w for _, w in signals)
    return sum(s * w for s, w in signals) / total_weight


def model(dbt, session):
    postings = dbt.ref("int_postings_all_sources").df()
    nuts_lookup = dbt.ref("int_nuts_lookup").df()
    nuts_lookup_by_id = dict(zip(nuts_lookup["nuts_id"], nuts_lookup["name_latn"]))

    postings["company_norm"] = [
        normalize_company(row.company_name, row.country_code) for row in postings.itertuples()
    ]
    postings["title_norm"] = [
        normalize_title(row.job_title, row.source_system) for row in postings.itertuples()
    ]
    eures_location = [
        resolve_eures_location(row.location_nuts_codes, nuts_lookup_by_id) for row in postings.itertuples()
    ]
    postings["location_norm"] = [
        normalize_location(row.location_text) if row.location_text else normalize_location(loc)
        for row, loc in zip(postings.itertuples(), eures_location)
    ]

    adzuna = postings[postings["source_system"] == "adzuna"]
    eures = postings[postings["source_system"] == "eures"]

    candidates = []
    for country, adzuna_group in adzuna.groupby("country_code"):
        eures_group = eures[eures["country_code"] == country]
        if eures_group.empty:
            continue
        for a in adzuna_group.itertuples():
            for b in eures_group.itertuples():
                if pd.notna(a.posted_at) and pd.notna(b.posted_at):
                    if abs((a.posted_at - b.posted_at).days) > POSTED_AT_WINDOW_DAYS:
                        continue
                if not shares_a_role(a, b):
                    continue
                score = pair_score(a, b)
                if score >= THRESHOLD:
                    candidates.append((score, a.source_posting_key, b.source_posting_key))

    candidates.sort(key=lambda x: -x[0])
    assigned = set()
    pair_of = {}
    score_of = {}
    for score, a_key, b_key in candidates:
        if a_key in assigned or b_key in assigned:
            continue
        assigned.add(a_key)
        assigned.add(b_key)
        pair_of[a_key] = b_key
        pair_of[b_key] = a_key
        score_of[a_key] = score
        score_of[b_key] = score

    def group_id(key):
        if key in pair_of:
            return "|".join(sorted([key, pair_of[key]]))
        return key

    postings["dedup_group_id"] = postings["source_posting_key"].map(group_id)
    postings["dedup_score"] = postings["source_posting_key"].map(score_of)

    return postings.drop(columns=["location_nuts_codes"])
