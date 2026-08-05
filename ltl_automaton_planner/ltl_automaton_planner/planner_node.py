"""ROS2 node wrapping the ROS-independent LTL planner core."""

from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import String

from ltl_automaton_planner_core.configuration.transition_system import (
    import_ts_from_file,
    state_models_from_ts,
)
from ltl_automaton_msgs.msg import (
    TransitionSystemStateStamped,
)
from ltl_automaton_planner_core.ltl_tools.ltl_planner import (
    LTLPlanner,
)
from ltl_automaton_planner_core.ltl_tools.ts import TSModel


class PlannerNode(Node):
    """Load a transition system and publish an initial LTL plan action."""

    def __init__(self):
        """Initialize the ROS2 planner node."""
        super().__init__("ltl_planner")

        self.declare_parameter(
            "transition_system_path",
            "",
        )
        self.declare_parameter(
            "hard_task",
            "",
        )
        self.declare_parameter(
            "soft_task",
            "",
        )
        self.declare_parameter(
            "beta",
            1000.0,
        )
        self.declare_parameter(
            "gamma",
            10.0,
        )

        command_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.next_move_publisher = self.create_publisher(
            String,
            "next_move_cmd",
            command_qos,
        )

        self.state_subscription = self.create_subscription(
            TransitionSystemStateStamped,
            "ts_state",
            self._ts_state_callback,
            10,
        )

        self.ltl_planner = None

        self._initialize_planner()

    def _initialize_planner(self):
        """Load the TS, run static planning, and publish the first action."""
        ts_path_value = self.get_parameter(
            "transition_system_path"
        ).value
        hard_task = self.get_parameter(
            "hard_task"
        ).value
        soft_task = self.get_parameter(
            "soft_task"
        ).value
        beta = self.get_parameter(
            "beta"
        ).value
        gamma = self.get_parameter(
            "gamma"
        ).value

        if not ts_path_value:
            self.get_logger().error(
                "Parameter 'transition_system_path' is required."
            )
            return

        if not hard_task:
            self.get_logger().error(
                "Parameter 'hard_task' is required."
            )
            return

        if not soft_task:
            self.get_logger().error(
                "Parameter 'soft_task' is required."
            )
            return

        ts_path = Path(ts_path_value).expanduser()

        if not ts_path.is_file():
            self.get_logger().error(
                f"Transition-system file does not exist: {ts_path}"
            )
            return

        try:
            with ts_path.open(
                "r",
                encoding="utf-8",
            ) as ts_file:
                ts_data = import_ts_from_file(
                    ts_file
                )

            state_models = state_models_from_ts(
                ts_data
            )
            transition_system = TSModel(
                state_models
            )

            self.ltl_planner = LTLPlanner(
                transition_system,
                hard_task,
                soft_task,
                beta=beta,  # type: ignore
                gamma=gamma,  # type: ignore
            )

            success = self.ltl_planner.optimal(
                style="static"
            )

        except Exception as error:
            self.get_logger().error(
                f"Planner initialization failed: {error}"
            )
            self.ltl_planner = None
            return

        if not success or self.ltl_planner.run is None:
            self.get_logger().error(
                "No accepting LTL plan was found."
            )
            return

        initial_states = (
            self.ltl_planner.product
            .graph["ts"]  # type: ignore
            .graph["initial"]
        )

        if initial_states:
            self.ltl_planner.curr_ts_state = next(
                iter(initial_states)
            )

        self.get_logger().info(
            "Initial LTL planning succeeded."
        )
        self.get_logger().info(
            f"Prefix actions: {self.ltl_planner.run.pre_plan}"
        )
        self.get_logger().info(
            f"Suffix actions: {self.ltl_planner.run.suf_plan}"
        )

        self._publish_next_move()

    @staticmethod
    def _state_from_message(message):
        """Convert a ROS TS-state message into a TS node tuple."""
        states = tuple(message.ts_state.states)
        dimensions = message.ts_state.state_dimension_names

        if not states:
            raise ValueError(
                "Received an empty transition-system state."
            )

        if len(states) != len(dimensions):
            raise ValueError(
                "The number of TS states does not match "
                "the number of state dimensions."
            )

        return states

    def _expected_next_state(self):
        """Return the TS state expected after the current action."""
        if (
            self.ltl_planner is None
            or self.ltl_planner.run is None
        ):
            return None

        run = self.ltl_planner.run
        index = self.ltl_planner.index

        if self.ltl_planner.segment == "line":
            next_index = index + 1

            if next_index >= len(run.line):
                return None

            return run.line[next_index]

        if self.ltl_planner.segment == "loop":
            next_index = index + 1

            if next_index >= len(run.loop):
                return None

            return run.loop[next_index]

        return None

    def _ts_state_callback(self, message):
        """Advance the plan when the expected TS state is reached."""
        if (
            self.ltl_planner is None
            or self.ltl_planner.run is None
        ):
            self.get_logger().warning(
                "Received a TS state before a plan was available."
            )
            return

        try:
            reached_state = self._state_from_message(message)
        except ValueError as error:
            self.get_logger().error(str(error))
            return

        expected_state = self._expected_next_state()

        if expected_state is None:
            self.get_logger().error(
                "The planner has no expected next TS state."
            )
            return

        if (
            reached_state == self.ltl_planner.curr_ts_state
            and reached_state != expected_state
        ):
            self.get_logger().debug(
                f"Ignoring repeated TS state: {reached_state}"
            )
            return

        if reached_state != expected_state:
            self.get_logger().warning(
                "Unexpected TS state. "
                f"Expected {expected_state}, "
                f"received {reached_state}. "
                "Replanning from the received state."
            )

            try:
                replanned = self.ltl_planner.replan_from_ts_state(
                    reached_state
                )
            except Exception as error:
                self.get_logger().error(
                    f"Replanning from {reached_state} failed: {error}"
                )
                return

            if (
                not replanned
                or self.ltl_planner.run is None
                or self.ltl_planner.next_move is None
            ):
                self.get_logger().error(
                    "No accepting plan was found from "
                    f"the unexpected state {reached_state}."
                )
                return

            self.ltl_planner.curr_ts_state = reached_state

            self.get_logger().info(
                f"Replanning succeeded from {reached_state}."
            )
            self.get_logger().info(
                f"Selected next move: {self.ltl_planner.next_move}"
            )

            self._publish_next_move()
            return

        self.ltl_planner.curr_ts_state = reached_state

        try:
            next_move = self.ltl_planner.find_next_move()
        except RuntimeError as error:
            self.get_logger().error(
                f"Failed to advance the plan: {error}"
            )
            return

        self.get_logger().info(
            f"Reached expected TS state: {reached_state}"
        )
        self.get_logger().info(
            f"Selected next move: {next_move}"
        )

        self._publish_next_move()

    def _publish_next_move(self):
        """Publish the currently selected planner action."""
        if (
            self.ltl_planner is None
            or self.ltl_planner.next_move is None
        ):
            self.get_logger().error(
                "No next action is available."
            )
            return

        message = String()
        message.data = str(
            self.ltl_planner.next_move
        )

        self.next_move_publisher.publish(
            message
        )

        self.get_logger().info(
            f"Published next move: {message.data}"
        )


def main(args=None):
    """Run the ROS2 planner node."""
    rclpy.init(args=args)

    node = PlannerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
