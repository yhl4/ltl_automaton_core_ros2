from io import StringIO

from ltl_automaton_planner_core.configuration.transition_system import (
    import_ts_from_file,
    state_models_from_ts,
)


TS_YAML = """
state_dim:
  - region

state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
      r2:
        connected_to: {}

actions:
  goto_r2:
    guard: "1"
    weight: 2.0
"""


def test_import_ts_from_yaml() -> None:
    ts_dict = import_ts_from_file(StringIO(TS_YAML))

    assert ts_dict["state_dim"] == ["region"]
    assert ts_dict["state_models"]["region"]["initial"] == "r1"


def test_create_state_model_from_ts() -> None:
    ts_dict = import_ts_from_file(StringIO(TS_YAML))
    state_models = state_models_from_ts(ts_dict)

    assert len(state_models) == 1

    region_model = state_models[0]

    assert set(region_model.nodes) == {
        ("r1",),
        ("r2",),
    }
    assert region_model.graph["initial"] == {("r1",)}

    assert region_model.has_edge(("r1",), ("r2",))

    edge = region_model[("r1",)][("r2",)]
    assert edge["action"] == "goto_r2"
    assert edge["guard"] == "1"
    assert edge["weight"] == 2.0


def test_override_initial_state() -> None:
    ts_dict = import_ts_from_file(StringIO(TS_YAML))

    state_models = state_models_from_ts(
        ts_dict,
        initial_states_dict={"region": "r2"},
    )

    assert state_models[0].graph["initial"] == {("r2",)}
