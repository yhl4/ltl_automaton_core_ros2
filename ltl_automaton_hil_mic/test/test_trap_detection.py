from types import SimpleNamespace

from ltl_automaton_msgs.msg import TransitionSystemState
from ltl_automaton_msgs.srv import TrapCheck
from networkx import DiGraph

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
