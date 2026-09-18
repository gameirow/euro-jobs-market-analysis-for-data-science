"""Daily Adzuna pull: current live postings for data scientist / data analyst /
business intelligence roles across target countries, written to data/raw/ as one
Parquet file per country per day.

No age filter — this grabs whatever is currently live each day. History and
staleness (question 7) come from diffing these daily files downstream, not from
anything this script does.

Rate-limit budgeting: Adzuna's free tier caps are 25/min, 250/day, 1000/week,
2500/month. Since this runs once a day via cron, the binding constraint is the
monthly average (~83 req/day) and weekly average (~142 req/day), not the 250/day
headline figure. MAX_PAGES_PER_QUERY=3 (150 results per role per country) keeps
the worst case at len(COUNTRIES) * len(ROLE_QUERIES) * MAX_PAGES_PER_QUERY = 72
requests/day even if every query maxes out every single day.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

COUNTRIES = ["ch", "de", "fr", "it", "es", "nl", "be", "pl", "at"]
ROLE_QUERIES = ["data scientist", "data analyst", "business intelligence"]

RESULTS_PER_PAGE = 50
MAX_PAGES_PER_QUERY = 3
MAX_REQUESTS_PER_RUN = 200  # hard circuit breaker, well under the 250/day cap
MIN_REQUEST_INTERVAL_SECONDS = 2.5  # keeps us under 25/min
MAX_RETRIES = 3
BACKOFF_SECONDS = 5

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("adzuna_ingest")


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


def load_credentials():
    load_dotenv(ROOT / ".env")
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        log.error("ADZUNA_APP_ID / ADZUNA_APP_KEY missing or blank in .env")
        sys.exit(1)
    return app_id, app_key


def fetch_page(country, page, query, app_id, app_key, limiter):
    """Returns the parsed JSON payload, or None if this page could not be fetched
    (rate limited past retry budget, unsupported country, network failure, ...).
    A None return means "stop paginating this query", not "crash the run"."""
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": RESULTS_PER_PAGE,
        "what_phrase": query,
        "content-type": "application/json",
    }
    url = BASE_URL.format(country=country, page=page)

    for attempt in range(1, MAX_RETRIES + 1):
        if limiter.budget_exhausted():
            log.warning("Request budget (%s) reached; stopping further calls.", limiter.max_requests)
            return None

        limiter.wait()
        try:
            resp = requests.get(url, params=params, timeout=30)
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
        if resp.status_code == 404:
            log.error("Country %r not supported by Adzuna: %s", country, resp.text[:200])
            return None

        log.warning("HTTP %s on %s p%s %r: %s", resp.status_code, country, page, query, resp.text[:200])
        time.sleep(BACKOFF_SECONDS * attempt)

    log.error("Giving up on %s p%s %r after %s attempts.", country, page, query, MAX_RETRIES)
    return None


def fetch_country(country, app_id, app_key, limiter):
    """Runs every role query for one country and de-dupes postings that match
    more than one query (e.g. a posting titled 'Data Analyst / BI Specialist')."""
    records = {}
    for query in ROLE_QUERIES:
        page = 1
        while page <= MAX_PAGES_PER_QUERY:
            if limiter.budget_exhausted():
                break
            payload = fetch_page(country, page, query, app_id, app_key, limiter)
            if payload is None:
                break
            results = payload.get("results", [])
            if not results:
                break

            for job in results:
                job_id = job.get("id")
                if job_id is None:
                    continue
                matched = records.setdefault(job_id, dict(job))
                roles = matched.get("_matched_role_queries", set())
                roles.add(query)
                matched["_matched_role_queries"] = roles

            total_count = payload.get("count", 0)
            if len(results) < RESULTS_PER_PAGE or page * RESULTS_PER_PAGE >= total_count:
                break
            page += 1

    return list(records.values())


def flatten(job):
    location = job.get("location") or {}
    company = job.get("company") or {}
    category = job.get("category") or {}
    area = location.get("area") or []
    return {
        "id": job.get("id"),
        "title": job.get("title"),
        "description": job.get("description"),
        "created": job.get("created"),
        "company_display_name": company.get("display_name"),
        "location_display_name": location.get("display_name"),
        "location_area": " > ".join(area) if area else None,
        "latitude": job.get("latitude"),
        "longitude": job.get("longitude"),
        "category_label": category.get("label"),
        "category_tag": category.get("tag"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "salary_is_predicted": job.get("salary_is_predicted"),
        "contract_type": job.get("contract_type"),
        "contract_time": job.get("contract_time"),
        "redirect_url": job.get("redirect_url"),
        "adref": job.get("adref"),
        "matched_role_queries": "|".join(sorted(job.get("_matched_role_queries", []))),
    }


STRING_COLUMNS = [
    "id", "title", "description", "created", "company_display_name",
    "location_display_name", "location_area", "category_label", "category_tag",
    "salary_is_predicted", "contract_type", "contract_time", "redirect_url",
    "adref", "matched_role_queries",
]
FLOAT_COLUMNS = ["latitude", "longitude", "salary_min", "salary_max"]
ALL_FLATTEN_COLUMNS = STRING_COLUMNS + FLOAT_COLUMNS


def write_country_parquet(country, jobs, pull_date):
    # Always write a file, even with zero rows: dbt's source for this country
    # is a glob over adzuna_{country}_*.parquet, and DuckDB errors with "No
    # files found" if the glob matches nothing at all — a genuine zero-match
    # day would otherwise break the daily build (verified this failure mode
    # on the EURES ingest, applying the same fix here defensively).
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"adzuna_{country}_{pull_date.isoformat()}.parquet"

    if jobs:
        df = pd.DataFrame(flatten(j) for j in jobs)
    else:
        log.info("No results for %s on %s; writing an empty file.", country, pull_date)
        df = pd.DataFrame(columns=ALL_FLATTEN_COLUMNS)

    # Pin dtypes explicitly: a column that's all-null on a given day (e.g. a
    # country with no contract_type data that day) otherwise gets an ambiguous
    # physical Parquet type, which can break DuckDB's multi-file glob read the
    # day another file for the same country has real values in that column.
    for col in STRING_COLUMNS:
        df[col] = df[col].astype("string")
    for col in FLOAT_COLUMNS:
        df[col] = df[col].astype("float64")
    df.insert(0, "country", pd.array([country] * len(df), dtype="string"))
    df.insert(1, "pulled_date", pd.array([pull_date.isoformat()] * len(df), dtype="string"))
    df.to_parquet(out_path, index=False)
    log.info("Wrote %s rows to %s", len(df), out_path)
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--countries",
        default=",".join(COUNTRIES),
        help="Comma-separated Adzuna country codes (default: all target countries).",
    )
    parser.add_argument(
        "--max-pages-per-query",
        type=int,
        default=MAX_PAGES_PER_QUERY,
        help="Override pagination depth per role query, e.g. for a one-off backfill.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=MAX_REQUESTS_PER_RUN,
        help="Hard cap on API requests for this run.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    global MAX_PAGES_PER_QUERY
    MAX_PAGES_PER_QUERY = args.max_pages_per_query
    countries = [c.strip() for c in args.countries.split(",") if c.strip()]

    app_id, app_key = load_credentials()
    limiter = RateLimiter(args.max_requests)
    pull_date = datetime.now(timezone.utc).date()

    summary = {}
    for country in countries:
        if limiter.budget_exhausted():
            log.warning("Request budget exhausted before reaching %s; skipping.", country)
            summary[country] = "skipped (budget)"
            continue
        try:
            jobs = fetch_country(country, app_id, app_key, limiter)
            write_country_parquet(country, jobs, pull_date)
            summary[country] = len(jobs)
        except Exception:
            log.exception("Unexpected failure ingesting %s; continuing with remaining countries.", country)
            summary[country] = "failed"

    log.info("Ingest summary for %s: %s", pull_date, summary)
    log.info("Total API requests used: %s / %s", limiter.request_count, limiter.max_requests)


if __name__ == "__main__":
    main()
