"""ROS 2 planner plugin providing connected trap-state checks."""

from networkx import has_path

from ltl_automaton_msgs.srv import TrapCheck


def flatten_state_dimensions(raw_dimensions):
    """Flatten single- and multi-model TS dimension formats."""
    dimensions = []
    for name in raw_dimensions:
        if isinstance(name, (list, tuple)):
            dimensions.extend(str(item) for item in name)
        else:
            dimensions.append(str(name))
    return dimensions


def state_tuple_from_message(state_message, expected_dimensions):
    """Validate and reorder a state message for the planner TS format."""
    expected_dimensions = flatten_state_dimensions(expected_dimensions)
    if len(state_message.states) != len(state_message.state_dimension_names):
        raise ValueError(
            "TS state count does not match its state-dimension count."
        )
    state_by_dimension = dict(
        zip(state_message.state_dimension_names, state_message.states)
    )
    if len(state_by_dimension) != len(state_message.state_dimension_names):
        raise ValueError("TS state dimension names must be unique.")
    if set(state_by_dimension) != set(expected_dimensions):
        raise ValueError(
            "TS state dimensions do not match the planner TS format."
        )
    return tuple(state_by_dimension[name] for name in expected_dimensions)


class TrapDetectionPlugin:
    """Classify connected TS states by reachability to an accepting cycle."""

    def __init__(self, ltl_planner, args=None):
        del args
        self.ltl_planner = ltl_planner
        self.node = None
        self.service = None

    def set_node(self, node):
        """Attach the ROS 2 planner node hosting this plugin."""
        self.node = node

    def init(self):
        """Validate that ROS communication can be initialized."""
        if self.node is None:
            raise RuntimeError("TrapDetectionPlugin requires set_node(node).")

    def set_sub_and_pub(self):
        """Create the legacy-compatible check_for_trap service."""
        self.service = self.node.create_service(
            TrapCheck,
            "check_for_trap",
            self.trap_check_callback,
        )

    def run_at_ts_update(self, ts_state):
        """Retain the plugin lifecycle hook; no update work is required."""
        del ts_state

    def trap_check_callback(self, request, response):
        """Populate connectivity and trap classification for a request."""
        product = self.ltl_planner.product
        expected_dimensions = product.graph["ts"].graph["ts_state_format"]
        try:
            ts_state = state_tuple_from_message(
                request.ts_state,
                expected_dimensions,
            )
        except ValueError as error:
            self.node.get_logger().warning(str(error))
            response.is_connected = False
            response.is_trap = False
            return response

        possible_states = product.get_possible_states(ts_state)
        response.is_connected = bool(possible_states)
        response.is_trap = bool(possible_states) and self._all_are_traps(
            possible_states
        )
        return response

    def _all_are_traps(self, possible_states):
        product = self.ltl_planner.product
        accepting_cycles = product.graph["accept_with_cycle"]
        for state in possible_states:
            if any(
                has_path(product, state, accepting_state)
                for accepting_state in accepting_cycles
            ):
                return False
        return True
