"""Run exactly one representative Office8 query and emit exact JSON evidence."""

import json

from ltl_automaton_cmr.engine import plan
from ltl_automaton_cmr.office import load_office_query


if __name__ == "__main__":
    query = load_office_query("D2")
    result = plan(query.model, arm="AP", family_prior=query.family_prior)
    output = result.to_dict()
    output["query"] = {"id": query.query_id, "hard_task": query.hard_task,
                       "dimension_names": list(query.dimension_names),
                       "family_prior": sorted(query.family_prior)}
    print(json.dumps(output, indent=2, sort_keys=True))
