-- Reconciles Adzuna and EURES onto one schema. Column choices:
--   - posting_id: varchar on both sides (Adzuna's is natively numeric but
--     cast here since EURES's never is — no shared ID space between sources,
--     this is NOT a claim that the two id systems overlap).
--   - description_text: Adzuna's capped-at-500-char snippet and EURES's
--     uncapped text share this column name for the sake of a single
--     matchable text field, but description_is_full tells them apart —
--     never assume equal-length comparability between sources without it.
--   - location_text (Adzuna) / location_nuts_codes (EURES): genuinely
--     different representations (human text vs. coded regions), reconciled
--     into comparable text only in the dedup step, via int_nuts_lookup —
--     not here, since that's matching logic, not a straight rename.
--   - salary_*/posting_url: EURES doesn't currently capture these; carried
--     through as null for eures rows rather than dropped, so Adzuna rows
--     don't lose real data for the sake of symmetry.
select
    {{ dbt_utils.generate_surrogate_key(['source_system', 'posting_snapshot_key']) }} as source_posting_key,
    source_system,
    posting_snapshot_key,
    posting_id,
    country_code,
    snapshot_date,
    job_title,
    description_text,
    description_is_full,
    posted_at,
    company_name,
    location_text,
    location_nuts_codes,
    salary_min,
    salary_max,
    salary_is_predicted,
    contract_type,
    contract_time,
    posting_url,
    matched_role_queries
from (
    select
        'adzuna'                as source_system,
        posting_snapshot_key,
        cast(posting_id as varchar) as posting_id,
        country_code,
        snapshot_date,
        job_title,
        description_snippet    as description_text,
        false                   as description_is_full,
        posted_at,
        company_name,
        coalesce(location_area_path, location_name) as location_text,
        cast(null as varchar)  as location_nuts_codes,
        salary_min,
        salary_max,
        salary_is_predicted,
        contract_type,
        contract_time,
        posting_url,
        matched_role_queries
    from {{ ref('int_postings_unioned') }}

    union all

    select
        'eures'                 as source_system,
        posting_snapshot_key,
        posting_id,
        country_code,
        snapshot_date,
        job_title,
        description_text,
        true                    as description_is_full,
        posted_at,
        company_name,
        cast(null as varchar)   as location_text,
        location_nuts_codes,
        cast(null as double)    as salary_min,
        cast(null as double)    as salary_max,
        cast(null as boolean)   as salary_is_predicted,
        contract_type,
        contract_time,
        cast(null as varchar)   as posting_url,
        matched_role_queries
    from {{ ref('int_eures_unioned') }}
) reconciled
