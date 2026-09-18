-- One row per (posting_id, snapshot_date, source_system, skill) where the
-- skill's pattern matched the posting's description_text. Now runs against
-- int_postings_deduped (both sources), not just Adzuna — a matched
-- cross-source duplicate still gets one skill-match row per source_system
-- (link-don't-merge: this bridge doesn't decide whether to dedupe when
-- rolling up, that's a marts-layer choice via dedup_group_id).
select
    {{ dbt_utils.generate_surrogate_key(['p.source_posting_key', 'd.skill_key']) }} as posting_skill_key,
    p.source_posting_key,
    p.source_system,
    p.posting_id,
    p.snapshot_date,
    p.country_code,
    p.dedup_group_id,
    d.category,
    d.skill_key
from {{ ref('int_postings_deduped') }} as p
cross join {{ ref('int_skill_dictionary') }} as d
where regexp_matches(p.description_text, d.pattern, 'i')
