"""Read persisted repair comparisons and DDS evidence with only the stdlib."""

import argparse
from fractions import Fraction
import json
from pathlib import Path
import zipfile

from experiments.cmr_ros2_search_entry import readback


def checked(condition, label):
    if not condition:
        raise AssertionError(label)


def main(output):
    native = readback.main(output)
    output = readback.native_path(output)
    current = readback.read(output / "comparison.json")
    plan = readback.read(output / "plan.json")
    old_root = Path(__file__).parent / "evidence/20261012"
    old_index = readback.read(old_root / "index.json")
    archive = old_root / old_index["archive"]["path"]
    checked(readback.digest(archive) == old_index["archive"]["sha256"],
            "pinned V7 archive bytes")
    manifest = readback.read(old_root / "archive_manifest.json")
    with zipfile.ZipFile(archive) as zipped:
        def old_json(name):
            data = zipped.read(name)
            expected = manifest["members"][name]
            checked(len(data) == expected["size"] and
                    readback.sha256_bytes(data) == expected["sha256"],
                    "baseline member bytes: " + name)
            return json.loads(data)

        baseline = old_json("qualified_continuation/comparison.json")
        old_plan = old_json("qualified_continuation/plan.json")
        checked(baseline["status"] == "PASSED", "qualified baseline report")
        checked(old_plan["records"] == plan["records"], "same selected input records")
        comparisons = []
        for old_cell, new_cell in zip(baseline["cells"], current["cells"]):
            key = (old_cell["instance_id"], old_cell["method"])
            checked(key == (new_cell["instance_id"], new_cell["method"]), "paired cell")
            for arm in readback.ARMS:
                prior = old_cell["arms"][arm]
                new = new_cell["arms"][arm]
                checked(prior["row"]["terminal_status"] == new["row"]["terminal_status"],
                        "same verdict: " + arm)
                checked(Fraction(prior["row"]["objective"]) == Fraction(new["row"]["objective"]),
                        "same exact objective: " + arm)
                checked(prior["row"]["initial_S0"] == new["row"]["initial_S0"] and
                        prior["row"]["instance_sha256"] == new["row"]["instance_sha256"],
                        "same input and initialization: " + arm)
                checked(prior["transport"] == new["transport"], "same complete witness: " + arm)
                checked(old_cell["certificate_replays"][arm]["status"] ==
                        new_cell["certificate_replays"][arm]["status"] == "PASS",
                        "both independent certificate replay verdicts: " + arm)
            before = old_cell["arms"]["ros2-v7"]
            after = new_cell["arms"]["ros2-v7"]
            checked(readback.normalized(before["row"]["rounds"]) ==
                    readback.normalized(after["row"]["rounds"]), "unchanged V7 scientific rounds")
            checked(len(before["search_work"]) == len(after["search_work"]), "same search rounds")
            for left, right in zip(before["search_work"], after["search_work"]):
                checked(all(left[name] == right[name] for name in readback.SEARCH_COUNTERS),
                        "same V7 heap/settlement/pruning counters")
            comparisons.append(dict(instance_id=key[0], method=key[1],
                objective=after["row"]["objective"], verdict=after["row"]["terminal_status"],
                witness_unchanged=True, scientific_rounds_unchanged=True,
                search_counters_unchanged=True,
                baseline_total_seconds=before["row"]["T_total"],
                repaired_total_seconds=after["row"]["T_total"]))

    dds = readback.read(output / "dds/dds_report.json")
    checked(dds["status"] == "PASSED" and dds["domain_id"] == 227 and
            len(dds["cases"]) == 3, "three isolated real DDS cases")
    expected_imports = {
        "execution_node": "ltl_automaton_execution/ltl_automaton_execution/execution_node.py",
        "fake_runtime": "ltl_automaton_execution/ltl_automaton_execution/fake_runtime.py",
        "execution_models": "ltl_automaton_execution/ltl_automaton_execution/models.py",
    }
    dds_rows = []
    for cell, pair in zip(dds["cases"], comparisons):
        request = cell["request"]
        checked((request["instance_id"], request["method"]) ==
                (pair["instance_id"], pair["method"]), "fixed DDS cell")
        disk = readback.read(output / "dds" / request["request_id"] / "dds_artifact.json")
        checked(cell == disk and disk["status"] == "PASSED", "terminal DDS artifact persisted")
        value = disk["driver"]["result"]
        checked(value["version_binding_id"] == plan["version_binding_id"] and
                value["version_binding_sha256"] == plan["version_binding_sha256"], "DDS version binding")
        checked(value["terminal_status"] == pair["verdict"] and
                Fraction(value["objective"]) == Fraction(pair["objective"]), "DDS verdict and exact cost")
        checked(disk["certificate_replay"]["status"] == "PASS" and
                disk["certificate_replay"]["certificate_hash"] == value["certificate_hash"],
                "DDS independent certificate replay")
        driver = disk["driver"]
        for role, source in expected_imports.items():
            checked(driver["module_sha256"][role] == plan["source_closure"][source],
                    "bound production import: " + role)
        expected = next(item["arms"]["ros2-v7"] for item in current["cells"]
                        if item["instance_id"] == request["instance_id"] and
                        item["method"] == request["method"])
        checked(value["concrete_lasso"] == expected["transport"]["concrete_lasso"],
                "DDS full witness equals paired runner")
        checked(value["planner_budget_seconds"] == 180 and value["outer_watchdog_seconds"] == 195,
                "DDS original method/watchdog budgets")
        dds_rows.append(dict(instance_id=request["instance_id"], method=request["method"],
            objective=value["objective"], certificate_replay="PASS",
            actions=len(driver["expected_actions"])))
    result = dict(schema="cmr-v7-audit-real-readback-v1", status="PASSED",
        baseline_commit="00fc5a91383b24f85d33aa81682af22e531234cf",
        baseline_execution_identity=old_index["execution_identity"],
        execution_identity=plan["execution_identity"], version_binding_id=plan["version_binding_id"],
        source_head=plan["source_head"], source_files=len(plan["source_closure"]),
        native_readback=native, paired_cells=comparisons, real_dds=dds_rows,
        method_workers=9, dds_method_workers=3, persisted_certificate_replays=12,
        formal_campaign_workers=0, provider_calls=0, default_changed=False)
    (output / "audit_readback.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
