from types import SimpleNamespace

from networkx import DiGraph
from std_msgs.msg import Bool

from ltl_automaton_hil_mic.inverse_reinforcement_learning import IRLPlugin


P0 = (("r1",), "b0")
P1 = (("r2",), "b1")
P2 = (("r3",), "b2")


class FakeProduct(DiGraph):
    def __init__(self):
        super().__init__()
        self.graph["ts"] = SimpleNamespace(
            graph={"ts_state_format": [["region"]]}
        )
        self.graph["initial"] = {P0}
        self.graph["beta"] = 10.0
        self.possible_states = {P0}
        self.add_edge(
            P0,
            P1,
            transition_cost=1.0,
            soft_task_dist=0.0,
            weight=1.0,
        )
        self.add_edge(
            P0,
            P2,
            transition_cost=1.0,
            soft_task_dist=2.0,
            weight=21.0,
        )

    def update_beta(self, beta):
        self.graph["beta"] = beta
        for source, target in self.edges():
            edge = self[source][target]
            edge["weight"] = (
                edge["transition_cost"] + beta * edge["soft_task_dist"]
            )


class FakePlanner:
    def __init__(self, replan_success=True):
        self.product = FakeProduct()
        self.beta = 10.0
        self.gamma = 5.0
        self.hard_spec = "hard"
        self.soft_spec = "soft"
        self.curr_ts_state = ("r1",)
        self.replan_success = replan_success
        self.replan_calls = []

    def replan_task(self, hard, soft, state):
        self.replan_calls.append((hard, soft, state, self.beta))
        return self.replan_success


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeNode:
    def __init__(self):
        self.logger = FakeLogger()
        self.publisher = FakePublisher()
        self.refresh_count = 0

    def get_logger(self):
        return self.logger

    def create_publisher(self, *args):
        del args
        return self.publisher

    def create_subscription(self, *args):
        return args

    def refresh_planner_outputs(self):
        self.refresh_count += 1


def _plugin(replan_success=True):
    planner = FakePlanner(replan_success)
    node = FakeNode()
    plugin = IRLPlugin(planner, {"max_run_buffer_size": 10})
    plugin.set_node(node)
    plugin.init()
    plugin.set_sub_and_pub()
    return plugin, planner, node


def test_irl_records_and_publishes_consistent_product_runs():
    plugin, planner, node = _plugin()
    plugin.learning_trigger_callback(Bool(data=True))

    plugin.run_at_ts_update(("r2",))

    assert plugin.possible_runs == {(P0, P1)}
    message = node.publisher.messages[-1]
    assert len(message.runs) == 1
    assert message.runs[0].ltl_states[-1].ts_state.states == ["r2"]
    assert message.runs[0].ltl_states[-1].ts_state.state_dimension_names == [
        "region"
    ]


def test_irl_beta_learning_uses_soft_distance_gradient(monkeypatch):
    plugin, planner, node = _plugin()
    del node
    monkeypatch.setattr(plugin, "_margin_suffix", lambda path, beta: (P0, P2))

    beta, sequence, matches = plugin.learn_beta({(P0, P1)})

    assert beta > planner.beta
    assert sequence[-1] == beta
    assert all(score == 1 for score in matches)


def test_irl_success_updates_planner_beta_and_refreshes_outputs(monkeypatch):
    plugin, planner, node = _plugin()
    plugin.possible_runs = {(P0, P1)}
    monkeypatch.setattr(
        plugin,
        "learn_beta",
        lambda runs: (42.0, [42.0], [2]),
    )

    assert plugin._learn_and_replan() is True
    assert planner.beta == 42.0
    assert planner.replan_calls == [("hard", "soft", ("r1",), 42.0)]
    assert node.refresh_count == 1


def test_irl_failed_replan_restores_beta(monkeypatch):
    plugin, planner, node = _plugin(replan_success=False)
    plugin.possible_runs = {(P0, P1)}
    monkeypatch.setattr(
        plugin,
        "learn_beta",
        lambda runs: (42.0, [42.0], [2]),
    )

    assert plugin._learn_and_replan() is False
    assert planner.beta == 10.0
    assert planner.product.graph["beta"] == 10.0
    assert node.refresh_count == 0
