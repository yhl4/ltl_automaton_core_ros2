"""Read the isolated CMR smoke artifact without executing either planner."""
import hashlib
import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(r"\\wsl.localhost\Ubuntu-22.04-D\tmp\ltl_cmr_ros2_smoke_1228773_20261011_fix1")

def native_path(value):
    if value.startswith('/mnt/c/') or value.startswith('/mnt/d/'):
        return Path(value[5].upper() + ':/' + value[7:])
    return Path(r"\\wsl.localhost\Ubuntu-22.04-D" + value.replace('/', '\\'))

raw = (ROOT / "result.json").read_bytes()
value = json.loads(raw)
assert value["schema"] == "cmr-ros2-integration-smoke-v1"
assert value["population"] == "SYNTHETIC_SMOKE"
assert value["status"] == "PASSED", value.get("error")
methods = ("FULL", "AP-D", "DEP-D")
variants = ("base", "initial_goal", "zero_cost", "no_accept")
expected_pairs = {(v, m) for v in variants for m in methods}
rows = value["rows"]
assert len(rows) == 12
assert {(r["variant"], r["method"]) for r in rows} == expected_pairs
for row in rows:
    expected = None if row["variant"] == "no_accept" else Fraction(
        0 if row["variant"] == "zero_cost" else 10)
    new, reference = row["new"], row["reference"]
    if expected is None:
        assert new is None and reference is None
        continue
    assert Fraction(new["lower_bound"]) == Fraction(reference["lower_bound"]) == expected
    assert Fraction(row["expected_cost"]) == expected
    for result in (new, reference):
        pre, suffix = result["prefix"], result["suffix"]
        assert pre and suffix and pre[-1] == suffix[0] == suffix[-1]
        assert len(suffix) == len(result["suffix_edges"]) + 1
        assert len(result["suffix_edges"]) > 0
        assert len(pre) == len(result["prefix_edges"]) + 1
        for states, edges in ((pre, result["prefix_edges"]), (suffix, result["suffix_edges"])):
            assert all(e["source"] == u and e["target"] == v
                       for u, e, v in zip(states, edges, states[1:]))
        p = sum((Fraction(e["cost"]) for e in result["prefix_edges"]), Fraction(0))
        s = sum((Fraction(e["cost"]) for e in result["suffix_edges"]), Fraction(0))
        assert p == Fraction(result["prefix_cost"])
        assert s == Fraction(result["suffix_cost"])
        assert p + 10 * s == Fraction(result["lower_bound"])
        assert any(q == "q_accept" for _, q in suffix[:-1])
        precision = [0] if row["method"] == "AP-D" else [0, 1]
        assert result["precision"] == precision
    if row["variant"] == "base":
        assert new["prefix"][-1][1] == "q_wait"
    assert row["suffix_nonempty"] and row["accepting_visited"]
    assert set(row["parallel_actions"]) == {"a_go", "b_go"}
    cert = row["certificate"]
    assert cert["status"] == "OPTIMALITY_CERTIFIED"
    assert Fraction(cert["lower_bound"]) == Fraction(cert["upper_bound"]) == expected
negative = value["negative_input_checks"]
assert len(negative) == 3
assert {(r["input"], r["actual"]) for r in negative} == {
    ("bool", "TypeError"), ("float", "TypeError"), ("negative", "ValueError")}
checks = value["manifest_preflight"]["source_checks"]
assert len(checks) == 40 and all(r["match"] for r in checks)
for row in checks:
    observed = native_path(row['path']).read_bytes()
    assert hashlib.sha256(observed).hexdigest() == row['expected_sha256']
imports = value["manifest_preflight"]["imports"]
assert len(imports) == 7
assert all(r["__file__"] == r["expected_path"] and
           r["sha256"] == r["expected_sha256"] for r in imports.values())
for row in imports.values():
    assert hashlib.sha256(native_path(row['__file__']).read_bytes()).hexdigest() == row['sha256']
frozen = json.loads((ROOT / 'frozen_inputs.json').read_bytes())
assert len(frozen['rows']) == 13
for row in frozen['rows']:
    observed = native_path(row['path']).read_bytes()
    assert len(observed) == row['size']
    assert hashlib.sha256(observed).hexdigest() == row['sha256']
assert (ROOT / 'smoke.rc').read_text().strip() == '0'
assert (ROOT / 'source_after.rc').read_text().strip() == '0'
assert json.loads((ROOT / 'source_after.json').read_bytes()) == {'all_match': True, 'files': 13}
result = {
    "status": "PASSED", "reader_scope": "JSON and exact arithmetic only; no planner import",
    "raw_artifact": {"path": str(ROOT / "result.json"), "size": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()},
    "matrix_rows": len(rows), "certified_synthetic_rows": 9,
    "no_accept_rows": 3, "negative_input_checks": len(negative),
    "source_hash_checks": len(checks), "actual_import_checks": len(imports),
    "frozen_input_checks": 13,
    "precision": {"FULL": [0, 1], "AP-D": [0], "DEP-D": [0, 1]},
}
out = Path(__file__).with_name("cmr_ros2_smoke_readback_20261011_fix1.json")
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
print(json.dumps(result))
