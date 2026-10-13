"""Directed feedback checks without ROS, solver calls or frozen evidence writes."""

from types import SimpleNamespace

from experiments.cmr_ros2_integration.dds_smoke import _Server


def _server():
    server = _Server.__new__(_Server)
    state = (("A",), "accept")
    server.snapshot = object()
    server.transitions = [(state, state, "wait", 0)] * 2
    server.state_ids = {state: 0}
    server.identity = "feedback-check"
    server.cursor = 0
    server.events = []
    server._feedback_after_ns = None
    server._last_state_stamp_ns = None
    server._feedback_step_seq = None
    server.clock_ns = 100
    server.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
        now=lambda: SimpleNamespace(nanoseconds=server.clock_ns)))
    server.PlanningExecutionObservation = SimpleNamespace
    server.String = lambda data: SimpleNamespace(data=data)
    server.observations = []
    server.observation_pub = SimpleNamespace(publish=server.observations.append)
    server.command_pub = SimpleNamespace(publish=lambda _: None)
    server._publish_observation()
    return server


def _message(stamp_ns, state="A"):
    return SimpleNamespace(
        header=SimpleNamespace(stamp=SimpleNamespace(
            sec=stamp_ns // 1_000_000_000, nanosec=stamp_ns % 1_000_000_000)),
        ts_state=SimpleNamespace(states=[state]),
    )


def test_replayed_feedback_cannot_complete_the_next_self_loop():
    server = _server()
    message = _message(150)
    server.clock_ns = 200
    server._state(message)
    assert server.cursor == 1
    server._state(message)
    assert server.cursor == 1
    assert [item.execution_step_seq for item in server.observations] == [0, 1]
    server.clock_ns = 300
    server._state(_message(250))
    assert server.cursor == 2
    assert [item.execution_step_seq for item in server.observations] == [0, 1, 2]


def test_feedback_must_be_newer_than_the_current_step():
    server = _server()
    server._state(_message(99))
    server._state(_message(100))
    assert server.cursor == 0
    server.clock_ns = 200
    server._state(_message(150))
    server._state(_message(180))
    server._state(_message(140))
    assert server.cursor == 1
    server.clock_ns = 300
    server._state(_message(250))
    assert server.cursor == 2


def test_republication_does_not_move_the_step_feedback_boundary():
    server = _server()
    server.clock_ns = 120
    server._publish_observation()
    server._state(_message(110))
    assert server.cursor == 1


def test_unexpected_or_terminal_feedback_does_not_advance():
    server = _server()
    server._state(_message(150, "B"))
    assert server.cursor == 0
    server.clock_ns = 200
    server._state(_message(150))
    server.clock_ns = 300
    server._state(_message(250))
    server._state(_message(350))
    assert server.cursor == 2
