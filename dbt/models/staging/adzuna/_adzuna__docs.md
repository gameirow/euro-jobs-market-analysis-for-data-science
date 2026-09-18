{% docs daily_snapshot_grain %}
One row per `(posting_id, snapshot_date)` — the same posting reappears once per
day it stays live in Adzuna's search results. A posting_id that stops
appearing in a day's pull is treated downstream as closed/filled, which feeds
question 7 (how long postings stay live) rather than being a data-quality
problem to filter out.
{% enddocs %}

{% docs posting_snapshot_key %}
Surrogate key over `(posting_id, snapshot_date)`, generated with
`dbt_utils.generate_surrogate_key`. This is the true primary key of this
model — `posting_id` alone is not unique here.
{% enddocs %}

{% docs posting_id %}
Adzuna's own posting id, cast to bigint. Recurs across every `snapshot_date`
the posting stays live.
{% enddocs %}

{% docs country_code %}
Two-letter Adzuna country code. Redundant with which staging model produced
the row, kept so it survives a downstream union.
{% enddocs %}

{% docs snapshot_date %}
The date of the daily pull that captured this posting as live. Not the
posting's creation date — see `posted_at` for that.
{% enddocs %}

{% docs job_title %}
The posting's job title, as written by the poster. Free text — not yet parsed
for seniority or role archetype.
{% enddocs %}

{% docs description_snippet %}
Adzuna returns only a snippet of the full job description, not the complete
text. Named to make that limitation explicit rather than implying full text.
{% enddocs %}

{% docs posted_at %}
Timestamp Adzuna reports the posting was created. Cast with `try_cast` so a
malformed value nulls out instead of failing the whole build.
{% enddocs %}

{% docs company_name %}
Employer display name as returned by Adzuna. Not yet deduplicated or matched
across naming variants.
{% enddocs %}

{% docs location_name %}
Adzuna's human-readable location label for the posting.
{% enddocs %}

{% docs location_area_path %}
Hierarchical location breadcrumb (e.g. "Schweiz > Zürich"), broadest to most
specific, joined with " > ".
{% enddocs %}

{% docs category_label %}
Adzuna's own job-category label (their taxonomy, not ours).
{% enddocs %}

{% docs category_tag %}
Adzuna's own job-category machine tag (their taxonomy, not ours).
{% enddocs %}

{% docs salary_min %}
Lower bound of the posting's salary range, in the posting's local currency.
Never blend with `salary_max` into a single "average" figure without
accounting for `salary_is_predicted`.
{% enddocs %}

{% docs salary_max %}
Upper bound of the posting's salary range, in the posting's local currency.
Never blend with `salary_min` into a single "average" figure without
accounting for `salary_is_predicted`.
{% enddocs %}

{% docs salary_is_predicted %}
True when Adzuna estimated the salary rather than the poster disclosing it.
Per project convention, estimated and disclosed salary are treated as
different things and never blended silently downstream.
{% enddocs %}

{% docs contract_type %}
Adzuna's contract type field (e.g. permanent, contract), where disclosed.
{% enddocs %}

{% docs contract_time %}
Adzuna's contract time field (e.g. full_time, part_time), where disclosed.
{% enddocs %}

{% docs posting_url %}
Adzuna redirect URL for the posting.
{% enddocs %}

{% docs matched_role_queries %}
Pipe-delimited list of which of the three ingest-time search phrases
(`data scientist`, `data analyst`, `business intelligence`) this posting
matched. Ingest metadata describing how we found the row, not a property of
the job itself.
{% enddocs %}
