The Office adapter uses the unchanged Office JSON model, task manifest and monitor compiler from [yhl4/CMR-LTL at dad230c2f54d9d5eb85d5e8dfd01e2d6c229afbc](https://github.com/yhl4/CMR-LTL/tree/dad230c2f54d9d5eb85d5e8dfd01e2d6c229afbc), with the original MIT code license included in this package and benchmark content attribution under CC BY 4.0. The exact engine uses the separately frozen qualified P1 kernel. The Office adapter does not import the Office runner or its separate exact_backend.

Office8 means the original eight queries D1鈥揇8. It has ten dimensions in the fixed order r, p, d, b, f, l, c, w, j, s. Here b is the temporary badge/pass, with desk and robot values. The manifest also contains other tasks; this integration exposes only D1鈥揇8. The representative validation executes D2, F(p=E), starting from the frozen complete initial state.

The fixed delivery family prior is RF = {0,1,2,3}, corresponding to robot, parcel, door and badge. This prior is declared in code_v4/design_new_local.py as R={0,1,2,3}. FULL, AP and FAMILY share the same model, actions and exact engine. Their S0 values are respectively all ten dimensions, the task AP support, and AP support union RF. AP starts D2 at {1}. The prior does not modify costs, action availability, refinement or the acceptance test.

Run one representative query from the repository root after installing the local package, or set PYTHONPATH to its package directory:

```powershell
$env:PYTHONPATH = (Resolve-Path .\ltl_automaton_cmr).Path
py -3.12 -m ltl_automaton_cmr.cli --office-query D2 --arm AP --output .\ltl_automaton_cmr\validation\office_d2_ap.json
py -3.12 -m pytest .\ltl_automaton_cmr\test\test_office_adapter.py
```

The output contains each round's dimensions, selected action occurrences, exact bounds, restoration choice and elapsed time, plus the validated concrete lasso. Fraction numerators and denominators are authoritative. Time measurements are ordinary floating-point seconds, separate from cost certification. The standalone examples/office_d2.py emits the same result to stdout; examples/office_d2.json documents the exact initial snapshot and query.

load_office_query(query_id="D2", initial_state=None) returns an OfficeQuery with model, task, hard_task, query_id, dimension_names, value_names, state_schema and family_prior. decode_state preserves each occurrence of a lasso state. An initial override must give all ten named values or ten encoded integers. Partial feedback, booleans, floats, unknown factors and unknown values are rejected. A complete snapshot is a planning start, not evidence of physical action success.

All 48 action identities remain distinct. Multiple assignments, such as wash_floor setting f=wet and w=empty, form one atomic transition. Read, Write and CostSupp are mapped independently to dimension IDs; action costs stay exact Fractions. Labels use the task's explicit factor=value APs. The core consumes the initial label before target labels, retains projected hidden action self-loops, and validates concrete action identities before handoff to execution.

This adapter loads a finite symbolic world. It does not infer Office factors from the legacy YAML state-name AP convention, or reduce multi-effect actions to one-dimensional TSModel steps. External execution must explicitly support every Office symbolic action and report a complete snapshot. A float64 ROS cost field cannot certify an exact bound; exact JSON evidence must remain available. D8 recurrence and other Office queries are supported by the manifest loader but are not run as benchmarks here. No source experiment data is modified.

Copied source paths and SHA-256 values:

| Local file | Source under cmr_repro/oct6/office_v4/code_v4 | SHA-256 |
| --- | --- | --- |
| assets/office_model.json | input/model.json | 8721d884aef3f24cb3e4969c2ea04aa089661578426c20b1732971cb87a5611e |
| assets/office_task_manifest.json | input/task_manifest.json | 2d60b53e54e939c92bbd68317aeed2eb9ca2fb83e0ff2223f28e6d2d180a673c |
| vendor/office_monitor_dsl.py | sources/monitor_dsl.py | 2025d63042d96b381350665bbf8cd8a6a284f6f2af16292f2a2dbf5edab6942b |

The JSON byte hashes are checked at load time. The monitor compiler copy is tested against its frozen byte hash.

Local representative validation on 2026-10-08: AP D2 completed in 98.7413 seconds, with precisions {1}, {0,1}, {0,1,2}, {0,1,2,3}; lower bounds 14,18,19,20; the final exact upper bound is 20. The prefix costs 10 and the nonempty standby suffix costs 1, giving 10 + 10*1 = 20. The serialized result is validation/office_d2_ap.json. A separate replay checked all nine serialized edges against the original model, the initial Product state, accepting suffix closure and exact numerator/denominator costs. The nine Office adapter checks passed in 0.20 seconds. No large FULL Office solve or query benchmark sweep was run.
