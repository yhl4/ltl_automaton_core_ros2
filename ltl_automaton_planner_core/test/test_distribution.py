"""Check the installed planner-core dependency contract."""

from importlib.metadata import metadata, requires


def test_distribution_declares_imported_runtime_dependencies():
    dependencies = {
        requirement.split(";")[0].split(" ")[0].lower()
        for requirement in requires("ltl_automaton_planner_core")
        if "extra ==" not in requirement
    }
    assert {"networkx", "ply", "pyyaml"} <= dependencies
    assert metadata("ltl_automaton_planner_core")["Requires-Python"] == ">=3.10"
