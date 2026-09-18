-- Column names align with the Adzuna staging schema where the concepts
-- genuinely match (company_name, contract_time, contract_type,
-- matched_role_queries, ...); fields with no Adzuna equivalent or a
-- different taxonomy (ESCO occupation codes vs Adzuna's category tags, NUTS
-- codes vs human-readable location names) keep EURES-accurate names instead
-- of being forced into a misleading match. posting_id stays varchar (EURES
-- ids are base64-ish strings, not numeric like Adzuna's) — the cross-source
-- union reconciles this, not staging.
select
    {{ dbt_utils.generate_surrogate_key(['id', 'pulled_date']) }} as posting_snapshot_key,
    id                                         as posting_id,
    country                                    as country_code,
    cast(pulled_date as date)                  as snapshot_date,
    title                                      as job_title,
    description                                as description_text,
    epoch_ms(try_cast(creation_date_ms as bigint))          as posted_at,
    epoch_ms(try_cast(last_modification_date_ms as bigint)) as last_modified_at,
    try_cast(number_of_posts as integer)       as number_of_posts,
    location_nuts_codes,
    eures_flag,
    job_categories_codes                       as occupation_codes,
    position_schedule_codes                    as contract_time,
    position_offering_code                     as contract_type,
    employer_name                              as company_name,
    employer_website,
    employer_sector_codes,
    available_languages,
    translation_type,
    matched_role_queries
from {{ source('eures', 'pl') }}
