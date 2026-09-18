-- Mirrors int_postings_unioned.sql, but for EURES's 11 per-country staging
-- models. Kept separate from int_postings_unioned rather than merged into it
-- directly, so each source's own union stays simple and testable before
-- reconciliation happens in int_postings_all_sources.
select * from {{ ref('stg_eures__ch') }}
union all
select * from {{ ref('stg_eures__de') }}
union all
select * from {{ ref('stg_eures__fr') }}
union all
select * from {{ ref('stg_eures__it') }}
union all
select * from {{ ref('stg_eures__es') }}
union all
select * from {{ ref('stg_eures__nl') }}
union all
select * from {{ ref('stg_eures__be') }}
union all
select * from {{ ref('stg_eures__pl') }}
union all
select * from {{ ref('stg_eures__pt') }}
union all
select * from {{ ref('stg_eures__dk') }}
union all
select * from {{ ref('stg_eures__at') }}
