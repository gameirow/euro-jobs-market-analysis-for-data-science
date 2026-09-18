"""Daily EURES pull: current live postings for data scientist / data analyst /
business intelligence roles across target countries, written to data/raw/ as
one Parquet file per country per day. Mirrors ingest/adzuna_ingest.py's
pattern and rate-limiting discipline.

EURES is not a registered/documented developer API like Adzuna's — it is the
JSON endpoint behind eures.europa.eu's own search UI (base URL
https://europa.eu/eures/api), reverse-engineered by third parties, no key
required. It's a EU public-sector jobs portal rather than a commercial
job board, and europa.eu's robots.txt does not disallow this path, but there
is no published rate limit or terms of service for third-party programmatic
use to defer to. MIN_REQUEST_INTERVAL_SECONDS below is therefore a
self-imposed conservative choice, not a documented requirement.

Keyword matching against this API does not do phrase matching in ANY scope,
verified empirically (2026-09-18): "data analyst" against DESCRIPTION scope
returned 46,000+ "matches" including welders and HR partners; even TITLE scope
matched "Koch (gn) Businessgastronomie" (a chef) against "business
intelligence" (the API appears to OR the individual words, not require the
phrase). Single-word TITLE queries DO filter as genuine literal substring
matches (verified against every result, not just the top few).

So this ingest uses a two-stage approach instead of trusting the API's own
filtering: query TITLE scope on a single distinctive word per role
(scientist / analyst / intelligence — chosen empirically as the smallest
candidate set per role that's still a guaranteed superset of the true phrase),
then apply our own word-boundary phrase regex against title+description
locally to keep only genuine matches. This is the same word-boundary
philosophy as dictionaries/skill_dictionary.yml, applied to role filtering
instead of skill extraction.

No age filter, matching the project's ingestion policy — pulls whatever is
currently live each day; the daily snapshot design handles staleness
downstream, not at ingestion.
"""

import argparse
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

COUNTRIES = ["ch", "de", "fr", "it", "es", "nl", "be", "pl", "pt", "dk", "at"]

# role phrase -> single anchor word used for the server-side TITLE search.
# Each anchor is empirically the smallest candidate set per role that is
# still guaranteed to contain every genuine phrase match (the phrase always
# contains its anchor word), verified against the DE market on 2026-09-18:
# scientist=265, analyst=900, intelligence=214 vs. "business" alone=2128 and
# "data" alone=1582 (which would cover two roles in one query, but pulls more
# total pages than scientist+analyst combined).
ROLE_ANCHORS = {
    "data scientist": "scientist",
    "data analyst": "analyst",
    "business intelligence": "intelligence",
}
ROLE_PATTERNS = {
    phrase: re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
    for phrase in ROLE_ANCHORS
}

SEARCH_URL = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
USER_AGENT = "euro-data-jobs-research-bot/1.0"

RESULTS_PER_PAGE = 50  # API max
MAX_PAGES_PER_QUERY = 10  # covers up to 500 candidates per anchor per country
MAX_REQUESTS_PER_RUN = 350  # circuit breaker; no published cap exists to size this against
MIN_REQUEST_INTERVAL_SECONDS = 1.5  # self-imposed, no published rate limit to defer to
MAX_RETRIES = 3
BACKOFF_SECONDS = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eures_ingest")


class RateLimiter:
    def __init__(self, max_requests):
        self.max_requests = max_requests
        self.last_request_at = 0.0
        self.request_count = 0

    def wait(self):
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def record(self):
        self.last_request_at = time.monotonic()
        self.request_count += 1

    def budget_exhausted(self):
        return self.request_count >= self.max_requests


def fetch_page(country, page, query, limiter):
    """Returns the parsed JSON payload, or None if this page could not be
    fetched. A None return means "stop paginating this query", not "crash"."""
    body = {
        "resultsPerPage": RESULTS_PER_PAGE,
        "page": page,
        "sortSearch": "MOST_RECENT",
        "keywords": [{"keyword": query, "specificSearchCode": "TITLE"}],
        "locationCodes": [country],
        "requestLanguage": "en",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        if limiter.budget_exhausted():
            log.warning("Request budget (%s) reached; stopping further calls.", limiter.max_requests)
            return None

        limiter.wait()
        try:
            resp = requests.post(
                SEARCH_URL, json=body, headers={"User-Agent": USER_AGENT}, timeout=20
            )
        except requests.RequestException as exc:
            limiter.record()
            log.warning(
                "Network error on %s p%s %r (attempt %s/%s): %s",
                country, page, query, attempt, MAX_RETRIES, exc,
            )
            time.sleep(BACKOFF_SECONDS * attempt)
            continue

        limiter.record()

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            log.warning("Rate limited on %s p%s %r; backing off.", country, page, query)
            time.sleep(BACKOFF_SECONDS * attempt * 2)
            continue

        log.warning("HTTP %s on %s p%s %r: %s", resp.status_code, country, page, query, resp.text[:200])
        time.sleep(BACKOFF_SECONDS * attempt)

    log.error("Giving up on %s p%s %r after %s attempts.", country, page, query, MAX_RETRIES)
    return None


def fetch_country(country, limiter):
    """Stage 1: pull every candidate from all 3 anchor-word searches
    (de-duped by id — a job can be a candidate under more than one anchor).
    Stage 2: apply the real phrase filter to every unique candidate against
    ALL 3 role phrases (not just the one tied to whichever anchor surfaced
    it), and drop candidates that don't genuinely match any of them."""
    candidates = {}
    for anchor_word in set(ROLE_ANCHORS.values()):
        page = 1
        while page <= MAX_PAGES_PER_QUERY:
            if limiter.budget_exhausted():
                break
            payload = fetch_page(country, page, anchor_word, limiter)
            if payload is None:
                break
            results = payload.get("jvs", [])
            if not results:
                break

            for job in results:
                job_id = job.get("id")
                if job_id is None:
                    continue
                candidates.setdefault(job_id, job)

            total_count = payload.get("numberRecords", 0)
            if len(results) < RESULTS_PER_PAGE or page * RESULTS_PER_PAGE >= total_count:
                break
            page += 1

    matched_jobs = []
    for job in candidates.values():
        text = f"{job.get('title') or ''} {job.get('description') or ''}"
        matched_roles = {phrase for phrase, pattern in ROLE_PATTERNS.items() if pattern.search(text)}
        if not matched_roles:
            continue  # false-positive candidate from the anchor word alone
        job = dict(job)
        job["_matched_role_queries"] = matched_roles
        matched_jobs.append(job)

    log.info(
        "%s: %s anchor candidates -> %s genuine role matches after phrase filtering",
        country, len(candidates), len(matched_jobs),
    )
    return matched_jobs


def flatten(job):
    location_map = job.get("locationMap") or {}
    employer = job.get("employer") or {}
    return {
        "id": job.get("id"),
        "title": job.get("title"),
        "description": job.get("description"),
        "creation_date_ms": job.get("creationDate"),
        "last_modification_date_ms": job.get("lastModificationDate"),
        "number_of_posts": job.get("numberOfPosts"),
        "location_countries": "|".join(sorted(location_map.keys())) if location_map else None,
        "location_nuts_codes": "|".join(sorted({c for codes in location_map.values() if codes for c in codes if c})) or None,
        "eures_flag": job.get("euresFlag"),
        "job_categories_codes": "|".join(job.get("jobCategoriesCodes") or []) or None,
        "position_schedule_codes": "|".join(job.get("positionScheduleCodes") or []) or None,
        "position_offering_code": job.get("positionOfferingCode"),
        "employer_name": employer.get("name"),
        "employer_website": employer.get("website"),
        "employer_sector_codes": "|".join(employer.get("sectorCodes") or []) or None,
        "available_languages": "|".join(job.get("availableLanguages") or []) or None,
        "translation_type": job.get("translationType"),
        "matched_role_queries": "|".join(sorted(job.get("_matched_role_queries", []))),
    }


STRING_COLUMNS = [
    "id", "title", "description", "location_countries", "location_nuts_codes",
    "job_categories_codes", "position_schedule_codes", "position_offering_code",
    "employer_name", "employer_website", "employer_sector_codes",
    "available_languages", "translation_type", "matched_role_queries",
]
NUMERIC_COLUMNS = ["creation_date_ms", "last_modification_date_ms", "number_of_posts"]
ALL_FLATTEN_COLUMNS = STRING_COLUMNS + NUMERIC_COLUMNS + ["eures_flag"]


def write_country_parquet(country, jobs, pull_date):
    # Always write a file, even with zero rows: dbt's source for this country
    # is a glob over eures_{country}_*.parquet, and DuckDB errors with "No
    # files found" if the glob matches nothing at all — a genuine zero-match
    # day (which happens; Italy hit this on 2026-09-17) would otherwise break
    # the daily build, not just leave that day's data sparse.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"eures_{country}_{pull_date.isoformat()}.parquet"

    if jobs:
        df = pd.DataFrame(flatten(j) for j in jobs)
    else:
        log.info("No genuine role matches for %s on %s; writing an empty file.", country, pull_date)
        df = pd.DataFrame(columns=ALL_FLATTEN_COLUMNS)

    # Same dtype-pinning discipline as adzuna_ingest.py: an all-null column on
    # a given day would otherwise get an ambiguous physical Parquet type and
    # could break a future multi-day glob read for this country.
    for col in STRING_COLUMNS:
        df[col] = df[col].astype("string")
    for col in NUMERIC_COLUMNS:
        df[col] = df[col].astype("float64")
    df["eures_flag"] = df["eures_flag"].astype("boolean")
    df.insert(0, "country", pd.array([country] * len(df), dtype="string"))
    df.insert(1, "pulled_date", pd.array([pull_date.isoformat()] * len(df), dtype="string"))
    df.to_parquet(out_path, index=False)
    log.info("Wrote %s rows to %s", len(df), out_path)
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--countries", default=",".join(COUNTRIES))
    parser.add_argument("--max-pages-per-query", type=int, default=MAX_PAGES_PER_QUERY)
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS_PER_RUN)
    return parser.parse_args()


def main():
    args = parse_args()
    global MAX_PAGES_PER_QUERY
    MAX_PAGES_PER_QUERY = args.max_pages_per_query
    countries = [c.strip() for c in args.countries.split(",") if c.strip()]

    limiter = RateLimiter(args.max_requests)
    pull_date = datetime.now(timezone.utc).date()

    summary = {}
    for country in countries:
        if limiter.budget_exhausted():
            log.warning("Request budget exhausted before reaching %s; skipping.", country)
            summary[country] = "skipped (budget)"
            continue
        try:
            jobs = fetch_country(country, limiter)
            write_country_parquet(country, jobs, pull_date)
            summary[country] = len(jobs)
        except Exception:
            log.exception("Unexpected failure ingesting %s; continuing with remaining countries.", country)
            summary[country] = "failed"

    log.info("Ingest summary for %s: %s", pull_date, summary)
    log.info("Total API requests used: %s / %s", limiter.request_count, limiter.max_requests)


if __name__ == "__main__":
    main()
