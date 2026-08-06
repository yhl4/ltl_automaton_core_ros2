"""Drive the KTH ROS2 planner demo with deterministic TS feedback."""

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import String

from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import TaskPlanning


STATE_DIMENSIONS = [
    "2d_pose_region",
    "turtlebot_load",
]
VALID_SCENARIOS = {
    "normal",
    "task_replanning",
    "deviation",
    "full",
}


def next_state_for_action(current_state, action):
    """Apply one KTH example action to a TS state."""
    region, load = current_state

    move_targets = {
        "goto_r1": "r1",
        "goto_r2": "r2",
        "goto_r3": "r3",
    }

    if action in move_targets:
        return move_targets[action], load

    if action == "pick" and region == "r2" and load == "unloaded":
        return region, "loaded"

    if action == "drop" and region == "r2" and load == "loaded":
        return region, "unloaded"

    raise ValueError(
        f"Action {action!r} is invalid from state {current_state!r}."
    )


class KthDemoDriver(Node):
    """Publish repeatable KTH-example feedback and request task replanning."""

    def __init__(self):
        """Initialize demo parameters and ROS interfaces."""
        super().__init__("kth_demo_driver")

        self.declare_parameter("scenario", "normal")
        self.declare_parameter("step_delay", 1.0)
        self.declare_parameter("max_steps", 8)
        self.declare_parameter("replanning_after_steps", 3)
        self.declare_parameter("replanning_hard_task", "<> r3")
        self.declare_parameter(
            "replanning_soft_task",
            "(r3 || ! r3)",
        )

        self.scenario = str(
            self.get_parameter("scenario").value
        )
        self.step_delay = float(
            self.get_parameter("step_delay").value
        )
        self.max_steps = int(
            self.get_parameter("max_steps").value
        )
        self.replanning_after_steps = int(
            self.get_parameter("replanning_after_steps").value
        )
        self.replanning_hard_task = str(
            self.get_parameter("replanning_hard_task").value
        )
        self.replanning_soft_task = str(
            self.get_parameter("replanning_soft_task").value
        )

        if self.scenario not in VALID_SCENARIOS:
            raise ValueError(
                f"Unknown scenario {self.scenario!r}; expected one of "
                f"{sorted(VALID_SCENARIOS)}."
            )

        if self.step_delay <= 0:
            raise ValueError("Parameter 'step_delay' must be positive.")

        if self.max_steps <= 0:
            raise ValueError("Parameter 'max_steps' must be positive.")

        state_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        command_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.state_publisher = self.create_publisher(
            TransitionSystemStateStamped,
            "ts_state",
            state_qos,
        )
        self.command_subscription = self.create_subscription(
            String,
            "next_move_cmd",
            self._next_move_callback,
            command_qos,
        )
        self.replanning_client = self.create_client(
            TaskPlanning,
            "replanning",
        )
        self.step_timer = self.create_timer(
            self.step_delay,
            self._step,
        )

        self.current_state = ("r1", "unloaded")
        self.pending_action = None
        self.completed_steps = 0
        self.replanning_requested = False
        self.replanning_succeeded = False
        self.deviation_published = False
        self.finished = False

        self.get_logger().info(
            f"KTH demo driver started with scenario={self.scenario!r}."
        )
        self.get_logger().info(
            f"Initial TS state: {self.current_state}."
        )

    def _next_move_callback(self, message):
        """Queue a planner action or trigger the scripted task change."""
        if self.finished:
            return

        if self._should_request_replanning():
            self._request_replanning()
            return

        if self.pending_action is None:
            self.pending_action = message.data
            self.get_logger().info(
                f"Received next move: {self.pending_action}."
            )

    def _should_request_replanning(self):
        """Return whether the selected scenario has reached its task switch."""
        return (
            self.scenario in {"task_replanning", "full"}
            and not self.replanning_requested
            and self.completed_steps >= self.replanning_after_steps
        )

    def _request_replanning(self):
        """Request the configured alternate task without blocking the node."""
        if not self.replanning_client.service_is_ready():
            self.get_logger().warning(
                "Replanning service is not ready; waiting for the next command."
            )
            return

        request = TaskPlanning.Request()
        request.hard_task = self.replanning_hard_task
        request.soft_task = self.replanning_soft_task

        self.replanning_requested = True
        self.get_logger().info(
            "Requesting task replanning: "
            f"hard={request.hard_task!r}, soft={request.soft_task!r}."
        )

        future = self.replanning_client.call_async(request)
        future.add_done_callback(self._replanning_done)

    def _replanning_done(self, future):
        """Record the task-replanning service result."""
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(
                f"Task replanning service failed: {error}"
            )
            return

        self.replanning_succeeded = bool(response.success)

        if self.replanning_succeeded:
            self.get_logger().info("Task replanning request succeeded.")
        else:
            self.get_logger().error("Task replanning request was rejected.")

    def _step(self):
        """Publish the state reached by the queued planner action."""
        if self.finished or self.pending_action is None:
            return

        action = self.pending_action
        self.pending_action = None

        try:
            reached_state = next_state_for_action(
                self.current_state,
                action,
            )
        except ValueError as error:
            self.get_logger().error(str(error))
            self.finished = True
            return

        reached_state = self._maybe_deviate(
            action,
            reached_state,
        )
        self._publish_state(reached_state)
        self.current_state = reached_state
        self.completed_steps += 1

        if self.completed_steps >= self.max_steps:
            self.finished = True
            self.get_logger().info(
                f"Demo completed after {self.completed_steps} state updates."
            )

    def _maybe_deviate(self, action, reached_state):
        """Replace one expected state with a legal KTH TS alternative."""
        if self.deviation_published:
            return reached_state

        if (
            self.scenario == "deviation"
            and self.current_state == ("r1", "unloaded")
            and action == "goto_r2"
        ):
            alternative = ("r3", "unloaded")
        elif (
            self.scenario == "full"
            and self.replanning_succeeded
            and self.current_state == ("r1", "loaded")
            and action == "goto_r3"
        ):
            alternative = ("r2", "loaded")
        else:
            return reached_state

        self.deviation_published = True
        self.get_logger().warning(
            f"Injecting legal deviation: expected {reached_state}, "
            f"publishing {alternative}."
        )
        return alternative

    def _publish_state(self, state):
        """Publish a two-dimensional KTH transition-system state."""
        message = TransitionSystemStateStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.ts_state.states = list(state)
        message.ts_state.state_dimension_names = STATE_DIMENSIONS

        self.state_publisher.publish(message)
        self.get_logger().info(f"Published TS state: {state}.")


def main(args=None):
    """Run the KTH demo driver node."""
    rclpy.init(args=args)
    node = KthDemoDriver()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
