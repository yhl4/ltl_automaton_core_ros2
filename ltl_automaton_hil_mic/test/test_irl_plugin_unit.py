"""Fake-host unit tests for the optional IRL plugin."""

from types import SimpleNamespace
import unittest

from ltl_automaton_msgs.msg import PlannerStatus
from networkx import DiGraph
from std_msgs.msg import Bool

from ltl_automaton_hil_mic.inverse_reinforcement_learning import IRLPlugin


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


class _FakeHost:
    def __init__(self, planner, buffer_size=100):
        self._planner_instance_id = "fake-instance"
        self._planning_generation = 1
        self._planner_state = PlannerStatus.ACTIVE
        self.ltl_planner = planner
        self.calls = []
        self.logger = _Logger()
        self.buffer_size = buffer_size

    def get_logger(self):
        return self.logger

    def create_publisher(self, *args):
        del args
        return _Publisher()

    def create_subscription(self, *args):
        del args
        return object()

    def start_irl_replan(self, possible_runs, identity):
        self.calls.append((set(possible_runs), tuple(identity)))
        return True


def _fake_planner():
    product = DiGraph()
    product.graph["ts"] = SimpleNamespace(
        graph={"ts_state_format": [["region"]]},
    )
    state = (("hub",), "q0")
    product.add_node(state)
    product.add_edge(state, state)
    product.possible_states = {state}
    return SimpleNamespace(product=product, curr_ts_state=("hub",))


def _fake_plugin(buffer_size=100):
    planner = _fake_planner()
    host = _FakeHost(planner, buffer_size=buffer_size)
    plugin = IRLPlugin(planner, {"max_run_buffer_size": buffer_size})
    plugin.set_node(host)
    plugin.init()
    plugin.set_sub_and_pub()
    return plugin, host, planner


class TestIRLPluginFakeHost(unittest.TestCase):
    """Exercise plugin lifecycle rules without a planner process."""

    def test_shared_composed_ts_values_keep_independent_published_lists(self):
        """Preserve ordered two-dimensional payloads and separate ROS state lists."""
        plugin, _, planner = _fake_plugin()
        planner.product.graph["ts"].graph["ts_state_format"] = [["region"], ["load"]]
        source_format = [["region"], ["load"]]
        ts_state = (("hub",), ("empty",))
        first, second = (ts_state, "q0"), (ts_state, "q1")
        plugin.possible_runs = {(first, first), (first, second), (second, second)}
        histories = set(plugin.possible_runs)
        plugin.publish_possible_runs()
        message = plugin.publisher.messages[-1]
        self.assertEqual(
            [[state.buchi_state for state in run.ltl_states] for run in message.runs],
            [["q0", "q0"], ["q0", "q1"], ["q1", "q1"]],
        )
        states = [state for run in message.runs for state in run.ltl_states]
        for state in states:
            self.assertEqual(state.ts_state.states, ["hub", "empty"])
            self.assertEqual(state.ts_state.state_dimension_names, ["region", "load"])
        self.assertEqual(len({id(state.ts_state.states) for state in states}), len(states))
        self.assertEqual(
            len({id(state.ts_state.state_dimension_names) for state in states}), len(states)
        )
        states[0].ts_state.states.append("caller_change")
        states[0].ts_state.state_dimension_names[0] = "caller_dimension_change"
        for state in states[1:]:
            self.assertEqual(state.ts_state.states, ["hub", "empty"])
            self.assertEqual(state.ts_state.state_dimension_names, ["region", "load"])
        self.assertEqual(plugin.possible_runs, histories)
        self.assertEqual(planner.product.graph["ts"].graph["ts_state_format"], source_format)
        plugin.publish_possible_runs()
        self.assertTrue(all(
            state.ts_state.states == ["hub", "empty"]
            and state.ts_state.state_dimension_names == ["region", "load"]
            for run in plugin.publisher.messages[-1].runs for state in run.ltl_states
        ))

    def test_converged_histories_keep_all_paths_and_read_changed_successors(self):
        """Keep distinct histories through a shared endpoint and fresh graph reads."""
        plugin, _, planner = _fake_plugin()
        product = planner.product
        hub = next(iter(product.possible_states))
        first = (("before_a",), "q0")
        second = (("before_b",), "q0")
        goal_a = (("goal",), "q1")
        goal_b = (("goal",), "q2")
        other = (("other",), "q1")
        product.add_edges_from([
            (first, first), (first, hub), (second, hub),
            (hub, goal_a), (hub, goal_b), (hub, other),
        ])
        histories = {(first, hub), (second, hub), (first, first, hub)}
        before = set(histories)
        expected = {run + (target,) for run in histories for target in (goal_a, goal_b)}
        edges = list(product.edges(data=True))
        self.assertEqual(plugin.update_possible_runs(histories, ("goal",)), expected)
        self.assertEqual(histories, before)
        self.assertEqual(list(product.edges(data=True)), edges)
        self.assertEqual(product.possible_states, {hub})
        self.assertEqual(plugin.update_possible_runs(histories, ("absent",)), set())

        product.remove_edge(hub, goal_a)
        self.assertEqual(
            plugin.update_possible_runs(histories, ("goal",)),
            {run + (goal_b,) for run in histories},
        )
        product.add_edge(hub, goal_a)
        self.assertEqual(plugin.update_possible_runs(histories, ("goal",)), expected)

    def test_empty_missing_and_duplicate_histories_keep_self_loop_semantics(self):
        """Skip invalid endpoints and deduplicate only identical complete paths."""
        plugin, _, planner = _fake_plugin()
        state = next(iter(planner.product.possible_states))
        missing = (("missing",), "q0")
        histories = [(), (missing,), (["unhashable"],), (state,), (state,)]
        self.assertEqual(plugin.update_possible_runs(histories, ("hub",)), {(state, state)})
        self.assertEqual(plugin.update_possible_runs(iter([(state,)]), ("hub",)), {(state, state)})
        self.assertEqual(plugin.update_possible_runs([], ("hub",)), set())
        self.assertEqual(planner.product.possible_states, {state})

    def test_records_successors_and_tracks_authority(self):
        """Record real Product successors and reset on generation changes."""
        plugin, host, planner = _fake_plugin()
        state = next(iter(planner.product.possible_states))

        self.assertIs(plugin.ltl_planner, planner)
        host.ltl_planner = _fake_planner()
        self.assertIs(plugin.ltl_planner, host.ltl_planner)
        plugin.learning_trigger_callback(Bool(data=True))
        plugin.run_at_ts_update(("hub",))

        self.assertEqual(plugin.possible_runs, {(state, state)})
        host._planning_generation = 2
        plugin.run_at_ts_update(("hub",))
        self.assertFalse(plugin.learning_trigger)
        self.assertEqual(plugin.possible_runs, {(state,)})

    def test_buffer_limit_and_repeated_bool_trigger_once(self):
        """A buffer overflow learns once and repeated Bool edges do nothing."""
        plugin, host, _ = _fake_plugin(buffer_size=2)
        plugin.learning_trigger_callback(Bool(data=True))
        plugin.learning_trigger_callback(Bool(data=True))
        plugin.run_at_ts_update(("hub",))
        plugin.run_at_ts_update(("hub",))

        self.assertEqual(len(host.calls), 1)
        self.assertFalse(plugin.learning_trigger)

        plugin.learning_trigger_callback(Bool(data=False))

        self.assertEqual(len(host.calls), 1)
        self.assertEqual(host.calls[0][1], ("fake-instance", 1))
        self.assertFalse(plugin.learning_trigger)
        plugin.learning_trigger_callback(Bool(data=False))
        self.assertEqual(len(host.calls), 1)

    def test_inconsistent_feedback_stops_recording_and_allows_fresh_restart(self):
        """Drop inconsistent teaching paths and restart from the current belief."""
        for finish_invalid_session in (False, True):
            with self.subTest(finish_invalid_session=finish_invalid_session):
                plugin, host, planner = _fake_plugin()
                state = next(iter(planner.product.possible_states))
                edges = list(planner.product.edges(data=True))
                possible_states = set(planner.product.possible_states)
                generation = host._planning_generation
                instance = host._planner_instance_id
                status = host._planner_state

                plugin.learning_trigger_callback(Bool(data=True))
                plugin.run_at_ts_update(("hub",))
                self.assertTrue(plugin.learning_trigger)
                self.assertEqual(plugin.possible_runs, {(state, state)})
                self.assertEqual(host.calls, [])
                published_count = len(plugin.publisher.messages)

                plugin.run_at_ts_update(("missing",))
                self.assertFalse(plugin.learning_trigger)
                self.assertEqual(plugin.possible_runs, set())
                self.assertEqual(host.calls, [])
                self.assertEqual(len(plugin.publisher.messages), published_count)

                plugin.run_at_ts_update(("hub",))
                if finish_invalid_session:
                    plugin.learning_trigger_callback(Bool(data=False))
                self.assertFalse(plugin.learning_trigger)
                self.assertEqual(host.calls, [])
                self.assertEqual(len(plugin.publisher.messages), published_count)

                plugin.learning_trigger_callback(Bool(data=True))
                self.assertTrue(plugin.learning_trigger)
                plugin.run_at_ts_update(("hub",))
                self.assertEqual(plugin.possible_runs, {(state, state)})
                plugin.learning_trigger_callback(Bool(data=False))

                self.assertFalse(plugin.learning_trigger)
                self.assertEqual(
                    host.calls,
                    [({(state, state)}, (instance, generation))],
                )
                self.assertEqual(list(planner.product.edges(data=True)), edges)
                self.assertEqual(planner.product.possible_states, possible_states)
                self.assertEqual(host._planner_instance_id, instance)
                self.assertEqual(host._planning_generation, generation)
                self.assertEqual(host._planner_state, status)
