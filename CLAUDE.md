# CLAUDE.md — European Data Job Market Pipeline

## What this project is

An end-to-end analytics engineering pipeline built as a portfolio piece. It ingests
European data-job postings daily, models them with dbt, and serves the results as a
public dashboard that refreshes on a schedule without human intervention.

The point is to demonstrate a **system**, not an analysis. The scheduled refresh, the
tests, the lineage docs and the public URL matter as much as the findings.

## Questions the project answers

1. What share of postings ask for each tool, and how does that share move over time?
2. Which skills co-occur? Cluster postings by skill vector to find the real role
   archetypes hiding behind inconsistent job titles.
3. How well does a job title predict required skills? Quantify the mismatch.
4. What does each market demand and how deep is it? (Zurich, Geneva, Munich,
   Paris, Milan, Barcelona, Amsterdam, Warsaw, Lisbon, Copenhagen)
5. What does "junior" actually mean? Parse required years of experience from
   description text and cross it against junior/graduate titles.
6. What share of postings are gated by a language requirement? German for Zurich,
   French for Romandie. This is the headline finding.
7. How long do postings stay live? Requires daily snapshots.

Questions 1 and 2 carry the project. Question 6 is the headline. The rest are bonus.

## Attribution requirement

Adzuna's terms require attribution wherever this data is published: link the phrase
"The Adzuna API" to adzuna.co.uk (or the relevant local domain) in the README and on
the Evidence site footer. João confirmed by email with Adzuna that this ongoing
personal portfolio use is fine.

## Stack (locked — do not substitute)

| Layer | Choice |
|---|---|
| Source | Adzuna developer API + EURES (europa.eu/eures/api, no key) |
| Raw storage | Parquet files, committed to the repo |
| Warehouse | DuckDB, rebuilt from raw in CI, **gitignored** |
| Transform | dbt Core + dbt-duckdb |
| Orchestration | GitHub Actions, daily cron |
| Serving (live) | Evidence, deployed to Netlify |
| Serving (secondary) | Power BI Desktop `.pbix` committed with screenshots |

Everything must stay on free tiers. No cloud warehouse, no hosted Airflow, no paid
services. If something appears to need payment, stop and ask rather than
substituting a paid tool.

Target countries: `ch, de, fr, it, es, nl, be, pl, pt, dk, at`. Coverage is
asymmetric between sources — Adzuna doesn't support `pt`/`dk` (verified against
the live API), so it pulls the other 9; EURES covers all 11. This is expected,
not a bug in either ingest script.

## Hard constraints

- **Do not scrape LinkedIn, Indeed, or any job board.** Official APIs only.
  Respect each API's rate limits (Adzuna free tier: 25/min, 250/day, 1000/week,
  2500/month).
  - (History: on 2026-09-18 this was briefly amended to allow fetching
    Adzuna's `redirect_url` to work around its 500-char description cap.
    Abandoned the same day, before it shipped — replaced by adding EURES as a
    second source, which has no such cap and needs no scraping at all. The
    amendment's text is gone; this note is what's left of it, in case the
    same recall problem resurfaces and someone's tempted to try that path
    again.)
- **No age-of-posting filter on ingestion.** This project is for market metrics, not
  personal job search, so pull broadly rather than restricting to recent postings.
  Older history strengthens the trend and market-depth questions (1 and 4).
  Staleness is handled downstream, not at ingestion: a posting that stops appearing
  in the daily pull is treated as closed/filled, which feeds question 7 rather than
  being a data-quality problem to filter out.
- **Never commit credentials.** Adzuna `app_id` and `app_key` live in `.env`
  (gitignored) locally and in GitHub Actions secrets for CI. If a secret is needed,
  tell me what to set and where; do not create accounts or enter keys yourself.
- **Never invent or synthesise data** to make a chart look better. If a field is
  sparse, say so and handle it explicitly.
- **Do not commit the DuckDB file.** Raw Parquet is the source of truth; the
  warehouse is a build artifact.
- Salary fields in Adzuna are sometimes estimated rather than disclosed. Treat
  estimated and actual salary as different things and never blend them silently.

## Data modelling requirements

The daily snapshot design is not optional — question 7 is impossible to retrofit.

- Raw layer: one Parquet file per pull, partitioned by date. Never mutated.
- Staging: one model per source, light typing and renaming only.
- Intermediate: skill extraction, seniority parsing, language-requirement detection.
- Marts: at minimum a posting fact table, a **daily posting snapshot fact table**,
  a company dimension, a location dimension, and a posting-to-skill bridge.

Skill extraction starts as a curated keyword dictionary, not an ML model. It has to
be inspectable and defensible in an interview. Fuzzy matching can come later if the
dictionary proves too brittle.

## Working agreement

- **Sessions are open-ended.** There is no schedule. We work until I say stop, then
  pick up later. End each session by summarising state and the obvious next step.
- **Scaffold before logic.** Build directory structure and configs first. Let me
  look before writing any model.
- **Explain modelling decisions before implementing them.** Incremental vs full
  refresh, what each test asserts, why a model sits in intermediate rather than
  marts. I have to defend all of this in interviews, so I need to understand it,
  not just have it.
- **Small commits, one concern each.** No giant drops.
- If I ask for something that would make the project worse, say so.

## Definition of done per layer

- **Ingest:** runs from a cold clone, writes a dated Parquet file, handles API
  errors and rate limits without crashing.
- **dbt:** `dbt build` passes with real tests (not_null, unique, relationships,
  accepted_values where meaningful). `dbt docs generate` produces a usable lineage
  graph.
- **Actions:** a scheduled run completes end to end with no local intervention.
- **Evidence:** the public site answers at least questions 1, 2 and 6 without me
  explaining anything to the viewer.
- **README:** question, answer, stack, then detail, plus the Adzuna attribution link.
  Written for a reader who stops after the first paragraph.

## Optional phase 2 — alerting, not auto-apply

Once the daily pull and marts exist, reuse them for a personal triage layer:

- Filter new postings each day against João's target skills/locations — SQL, Python,
  Power BI, dbt, data analyst/scientist/BI roles, Switzerland + open to relocating
  across Europe.
- Filter to recency for this use case specifically (configurable, default ~7 days)
  — unlike the main pipeline, which pulls broadly with no age filter.
- For matches, optionally draft a first-pass tailoring note against his CV
  (which real bullets to lead with, which gaps to disclose) so he isn't starting
  from a blank page.
- Surface matches for review — email digest, a simple local list, whatever's
  easiest. He decides what to apply to and submits it himself.

**Never auto-submit an application.** No form-filling, no browser automation
against company ATS pages, no scripted submission of any kind. This feature
automates search and triage only — never the decision to apply or the act of
applying.

## Environment notes

Windows, PowerShell. Project lives at C:\dev\euro-data-jobs (deliberately outside
OneDrive-synced folders to avoid file-lock/sync issues during builds).

## Tone

Be direct. Flag problems early. If a choice here is wrong, argue against it rather
than implementing it quietly.
