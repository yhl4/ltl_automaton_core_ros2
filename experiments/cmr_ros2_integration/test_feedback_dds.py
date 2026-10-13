"""Two isolated DDS transport fixtures; no CMR solver or certificate claim."""

from fractions import Fraction
import time

import pytest

from experiments.cmr_ros2_integration.dds_smoke import _Server, _snapshot_messages


@pytest.mark.parametrize("repeated_entry", [False, True])
def test_dds_repeated_targets_reject_replayed_feedback(tmp_path, repeated_entry):
    """Keep both zero-cost actions and accept only fresh per-step TS feedback."""
    import rclpy
    from ltl_automaton_msgs.msg import TransitionSystemStateStamped
    from ltl_automaton_execution.execution_node import ExecutionManagerNode
    from ltl_automaton_execution.models import ExecutionCompletion

    p = (("A",), "accept")
    q = p if repeated_entry else (("A",), "other")
    states = [p, q, p]
    edges = [dict(source=source, target=target, action="wait", cost="0")
             for source, target in zip(states, states[1:])]
    result = dict(concrete_lasso=dict(prefix=[p], suffix=states,
                                     prefix_edges=[], suffix_edges=edges),
                  accepting_buchi_states=["accept"])
    calls = []

    class Backend:
        def execute(self, step, completion):
            calls.append(step)
            completion(ExecutionCompletion(True, "completed"))
            return True

    class Observer:
        def start(self, callback):
            pass

        def stop(self):
            pass

    rclpy.init()
    server = execution = publisher_node = None
    try:
        server = _Server(dict(request_id="audit-feedback"), "", "", tmp_path)
        server.done = True  # No request may invoke a solver in this fixture.
        server.snapshot, server.transitions, server.state_ids = _snapshot_messages(
            result, server.identity)
        execution = ExecutionManagerNode(backend=Backend(), state_observer=Observer())
        publisher_node = rclpy.create_node("audit_feedback_publisher")
        publisher = publisher_node.create_publisher(TransitionSystemStateStamped,
                                                    "/ts_state", 10)
        server.executor.add_node(execution)
        server.executor.add_node(publisher_node)

        def wait_for(predicate):
            deadline = time.monotonic() + 8.0
            while not predicate() and time.monotonic() < deadline:
                server.executor.spin_once(timeout_sec=0.02)
            assert predicate(), server.events

        wait_for(lambda: server.observation_pub.get_subscription_count() > 0
                 and publisher.get_subscription_count() > 0
                 and execution._snapshot_client.service_is_ready())
        server._publish_observation()
        wait_for(lambda: len(calls) == 1)
        assert server.snapshot.accepted_run.suffix_product_node_ids == [
            server.state_ids[p], server.state_ids[q]]
        assert Fraction(str(server.snapshot.accepted_run.total_cost)) == 0
        first = TransitionSystemStateStamped()
        first.header.stamp = publisher_node.get_clock().now().to_msg()
        first.ts_state.state_dimension_names = ["factor0"]
        first.ts_state.states = ["A"]
        publisher.publish(first)
        wait_for(lambda: server.cursor == 1 and len(calls) == 2)
        publisher.publish(first)
        wait_for(lambda: any(event["event"] == "stale_ts_ignored"
                            for event in server.events))
        assert server.cursor == 1
        assert len(calls) == 2
        second = TransitionSystemStateStamped()
        second.header.stamp = publisher_node.get_clock().now().to_msg()
        second.ts_state.state_dimension_names = ["factor0"]
        second.ts_state.states = ["A"]
        publisher.publish(second)
        wait_for(lambda: server.cursor == 2)
        assert [step.execution_step_seq for step in calls] == [0, 1]
        assert [step.action for step in calls] == ["wait", "wait"]
    finally:
        if server is not None:
            server.executor.shutdown()
        for node in (execution, publisher_node, server.node if server else None):
            if node is not None:
                node.destroy_node()
        rclpy.shutdown()
