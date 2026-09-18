"""Loads dictionaries/nuts_lookup.csv — Eurostat's NUTS 2021 correspondence
table, merged with NUTS 2024 for the codes EURES has already moved to (the
Netherlands' 2024 NUTS 3 boundary revision in particular). See the CSV's
sibling build script / this project's conversation history for the
2021-vs-2024 coverage check (93% -> 100% observed against real EURES data).

Path is relative to the dbt invocation's working directory, same convention
as int_skill_dictionary.py and sources.yml's external_location paths.
"""

from pathlib import Path

import pandas as pd

NUTS_LOOKUP_PATH = Path("../dictionaries/nuts_lookup.csv")


def model(dbt, session):
    return pd.read_csv(NUTS_LOOKUP_PATH)
