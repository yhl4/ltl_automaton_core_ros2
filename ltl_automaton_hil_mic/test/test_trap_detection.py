from types import SimpleNamespace

from ltl_automaton_msgs.msg import TransitionSystemState
from ltl_automaton_msgs.srv import TrapCheck
from networkx import DiGraph, NodeNotFound, has_path
import pytest

from ltl_automaton_hil_mic.trap_detection import (
    TrapDetectionPlugin,
    flatten_state_dimensions,
    state_tuple_from_message,
)


class FakeProduct(DiGraph):
    def __init__(self):
        super().__init__()
        self.graph["ts"] = SimpleNamespace(
            graph={"ts_state_format": ["region", "load"]}
        )
        self.graph["accept_with_cycle"] = {"accept"}
        self.add_edges_from(
            [
                ("safe", "accept"),
                ("accept", "accept"),
            ]
        )
        self.add_node("trap")

    @staticmethod
    def get_possible_states(ts_state):
        return {
            ("r_safe", "loaded"): {"safe"},
            ("r_trap", "loaded"): {"trap"},
        }.get(ts_state, set())


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


class FakeNode:
    def __init__(self):
        self.logger = FakeLogger()
        self.service_args = None

    def get_logger(self):
        return self.logger

    def create_service(self, *args):
        self.service_args = args
        return object()


def _request(region, load="loaded", dimensions=("load", "region")):
    values = {"region": region, "load": load}
    return TrapCheck.Request(
        ts_state=TransitionSystemState(
            states=[values[name] for name in dimensions],
            state_dimension_names=list(dimensions),
        )
    )


def _plugin():
    plugin = TrapDetectionPlugin(
        SimpleNamespace(product=FakeProduct()),
        {},
    )
    node = FakeNode()
    plugin.set_node(node)
    plugin.init()
    plugin.set_sub_and_pub()
    return plugin, node


def test_state_message_is_reordered_to_planner_format():
    state = TransitionSystemState(
        states=["loaded", "r1"],
        state_dimension_names=["load", "region"],
    )
    assert state_tuple_from_message(state, ["region", "load"]) == (
        "r1",
        "loaded",
    )


def test_composed_ts_dimension_format_is_flattened():
    assert flatten_state_dimensions([["region"], ["load"]]) == [
        "region",
        "load",
    ]
    state = TransitionSystemState(
        states=["loaded", "r1"],
        state_dimension_names=["load", "region"],
    )
    assert state_tuple_from_message(
        state, [["region"], ["load"]]
    ) == ("r1", "loaded")


def test_trap_service_classifies_safe_trap_and_disconnected_states():
    plugin, node = _plugin()
    assert node.service_args[0] is TrapCheck
    assert node.service_args[1] == "check_for_trap"

    safe = plugin.trap_check_callback(
        _request("r_safe"), TrapCheck.Response()
    )
    assert safe.is_connected is True
    assert safe.is_trap is False

    trap = plugin.trap_check_callback(
        _request("r_trap"), TrapCheck.Response()
    )
    assert trap.is_connected is True
    assert trap.is_trap is True

    disconnected = plugin.trap_check_callback(
        _request("missing"), TrapCheck.Response()
    )
    assert disconnected.is_connected is False
    assert disconnected.is_trap is False


def test_trap_service_rejects_malformed_dimensions():
    plugin, node = _plugin()
    response = plugin.trap_check_callback(
        _request("r_safe", dimensions=("region",)),
        TrapCheck.Response(),
    )
    assert response.is_connected is False
    assert response.is_trap is False
    assert node.logger.warnings


def test_trap_diagnosis_uses_replacement_planner_authority():
    """Read the active planner after PlanLTL replaces its planner object."""
    plugin, node = _plugin()
    before = plugin.trap_check_callback(_request("r_safe"), TrapCheck.Response())
    assert not before.is_trap
    replacement = FakeProduct()
    replacement.remove_edge("safe", "accept")
    node.ltl_planner = SimpleNamespace(product=replacement)
    after = plugin.trap_check_callback(_request("r_safe"), TrapCheck.Response())
    assert after.is_connected
    assert after.is_trap


def test_trap_diagnosis_has_no_authority_without_active_planner():
    """Return a disconnected result while no committed planner exists."""
    plugin, node = _plugin()
    node.ltl_planner = None
    response = plugin.trap_check_callback(_request("r_safe"), TrapCheck.Response())
    assert not response.is_connected
    assert not response.is_trap


@pytest.mark.parametrize(
    "edges, possible, accepting, expected",
    [
        ([(0, 1), (1, 2), (2, 2)], {0}, {2}, False),
        ([(0, 1), (1, 0), (2, 2)], {0, 1}, {2}, True),
        ([(0, 1), (1, 2), (2, 2), (3, 3)], {0, 3}, {2}, False),
        ([(0, 1), (2, 2), (3, 3)], {0}, {2, 3}, True),
        ([(0, 1), (1, 1), (2, 2)], {0}, {1, 2}, False),
        ([(2, 2)], {2}, {2}, False),
        ([(2, 2)], set(), {2}, True),
        ([(0, 1)], {0}, set(), True),
        ([(2, 0), (2, 2)], {0}, {2}, True),
    ],
)
def test_trap_reachability_uses_any_candidate_and_accepting_cycle(
    edges, possible, accepting, expected
):
    """Preserve reachability direction, mixed candidates, cycles and empty boundaries."""
    plugin, _ = _plugin()
    product = DiGraph()
    product.add_nodes_from(range(4))
    product.add_edges_from(edges)
    product.graph["accept"] = {1, 2}
    product.graph["accept_with_cycle"] = accepting
    assert plugin._all_are_traps(possible, product) is expected


@pytest.mark.parametrize("source, target", [("missing", "accept"), ("safe", "missing")])
def test_missing_trap_graph_node_preserves_path_diagnostic(source, target):
    """A missing query endpoint must retain the original NetworkX exception."""
    plugin, _ = _plugin()
    product = FakeProduct()
    product.graph["accept_with_cycle"] = {target}
    with pytest.raises(NodeNotFound) as expected:
        has_path(product, source, target)
    with pytest.raises(NodeNotFound) as actual:
        plugin._all_are_traps({source}, product)
    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize(
    "possible, accepting",
    [
        (["safe", "missing"], ["accept"]),
        (["safe"], ["accept", "missing"]),
    ],
)
def test_safe_path_still_short_circuits_later_missing_graph_nodes(possible, accepting):
    """An earlier valid witness must keep the original successful short circuit."""
    plugin, _ = _plugin()
    product = FakeProduct()
    product.graph["accept_with_cycle"] = accepting
    assert plugin._all_are_traps(possible, product) is False


def test_trap_reachability_is_recomputed_after_graph_and_cycle_set_changes():
    """Repeated queries must see changes even when the Product object stays the same."""
    plugin, _ = _plugin()
    product = FakeProduct()
    assert plugin._all_are_traps({"safe"}, product) is False
    product.remove_edge("safe", "accept")
    assert plugin._all_are_traps({"safe"}, product) is True
    product.add_edge("safe", "accept")
    assert plugin._all_are_traps({"safe"}, product) is False
    product.graph["accept_with_cycle"] = set()
    assert plugin._all_are_traps({"safe"}, product) is True
