-- Unions the 8 per-country staging models into one cross-country posting
-- snapshot stream. Grain stays exactly what staging established: one row per
-- (posting_id, snapshot_date), identified by posting_snapshot_key.
select * from {{ ref('stg_adzuna__ch') }}
union all
select * from {{ ref('stg_adzuna__de') }}
union all
select * from {{ ref('stg_adzuna__fr') }}
union all
select * from {{ ref('stg_adzuna__it') }}
union all
select * from {{ ref('stg_adzuna__es') }}
union all
select * from {{ ref('stg_adzuna__nl') }}
union all
select * from {{ ref('stg_adzuna__be') }}
union all
select * from {{ ref('stg_adzuna__pl') }}
