"""ROS2 node wrapping the ROS-independent LTL planner core."""

import hashlib
import importlib
from pathlib import Path
from threading import RLock

import rclpy
import yaml
from rcl_interfaces.msg import SetParametersResult
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
    LTLPlan,
    LTLState,
    LTLStateArray,
    PlannerStatus,
    TransitionSystemState,
    TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import LoadTransitionSystem, TaskPlanning
from ltl_automaton_planner_core.ltl_tools.ltl_planner import (
    LTLPlanner,
)
from ltl_automaton_planner_core.ltl_tools.ts import TSModel


def initial_states_from_message(message) -> dict[str, str]:
    """Convert a stamped TS-state message into a dimension mapping."""
    states = list(message.ts_state.states)
    dimensions = list(message.ts_state.state_dimension_names)

    if not states:
        raise ValueError(
            "Received an empty transition-system state."
        )

    if len(states) != len(dimensions):
        raise ValueError(
            "The number of TS states does not match "
            "the number of state dimensions."
        )

    if len(set(dimensions)) != len(dimensions):
        raise ValueError(
            "Transition-system state dimensions must be unique."
        )

    return dict(zip(dimensions, states))


def load_plugin_specs(config_path) -> dict:
    """Load and validate a ROS2 planner-plugin configuration file."""
    path = Path(config_path).expanduser()

    if not path.is_file():
        raise ValueError(
            f"Plugin configuration file does not exist: {path}"
        )

    with path.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    if not isinstance(config, dict):
        raise ValueError("Plugin configuration must be a mapping.")

    plugin_specs = config.get("plugins", {})

    if not isinstance(plugin_specs, dict):
        raise ValueError("The 'plugins' entry must be a mapping.")

    for class_name, spec in plugin_specs.items():
        if not isinstance(class_name, str) or not class_name:
            raise ValueError("Plugin class names must be non-empty strings.")

        if not isinstance(spec, dict):
            raise ValueError(
                f"Configuration for plugin {class_name!r} must be a mapping."
            )

        if not isinstance(spec.get("path"), str) or not spec["path"]:
            raise ValueError(
                f"Plugin {class_name!r} requires a module 'path'."
            )

        if not isinstance(spec.get("args", {}), dict):
            raise ValueError(
                f"Plugin {class_name!r} 'args' must be a mapping."
            )

    return plugin_specs


class PlannerNode(Node):
    """Load a transition system and publish an initial LTL plan action."""

    def __init__(self, **kwargs):
        """Initialize the ROS2 planner node."""
        super().__init__("ltl_planner", **kwargs)

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
        self.declare_parameter(
            "initial_ts_state_from_agent",
            False,
        )
        self.declare_parameter(
            "replan_on_unplanned_move",
            True,
        )
        self.declare_parameter(
            "check_timestamp",
            True,
        )
        self.declare_parameter(
            "plugin_config_path",
            "",
        )

        command_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self._state_lock = RLock()
        self._planner_state = PlannerStatus.UNINITIALIZED
        self._active_transition_system = None
        self._active_ts_yaml = ""
        self._active_ts_sha256 = ""

        self.next_move_publisher = self.create_publisher(
            String,
            "next_move_cmd",
            command_qos,
        )

        self.prefix_plan_publisher = self.create_publisher(
            LTLPlan,
            "prefix_plan",
            command_qos,
        )

        self.suffix_plan_publisher = self.create_publisher(
            LTLPlan,
            "suffix_plan",
            command_qos,
        )

        self.possible_states_publisher = self.create_publisher(
            LTLStateArray,
            "possible_ltl_states",
            command_qos,
        )

        self.planner_status_publisher = self.create_publisher(
            PlannerStatus,
            "planner_status",
            command_qos,
        )

        self.state_subscription = self.create_subscription(
            TransitionSystemStateStamped,
            "ts_state",
            self._ts_state_callback,
            10,
        )

        self.replanning_service = self.create_service(
            TaskPlanning,
            "replanning",
            self._task_replanning_callback,
        )

        self.load_transition_system_service = self.create_service(
            LoadTransitionSystem,
            "load_transition_system",
            self._load_transition_system_callback,
        )

        self.ltl_planner = None
        self.plugins = {}
        self._plugins_initialized = False
        self.replan_on_unplanned_move = bool(
            self.get_parameter(
                "replan_on_unplanned_move"
            ).value
        )
        self.check_timestamp = bool(
            self.get_parameter("check_timestamp").value
        )
        self._previous_state_stamp = None
        self.add_on_set_parameters_callback(
            self._parameter_update_callback
        )
        self._waiting_for_initial_state = bool(
            self.get_parameter(
                "initial_ts_state_from_agent"
            ).value
        )

        self._set_planner_status(
            PlannerStatus.UNINITIALIZED,
            "No active transition system is loaded.",
        )

        ts_path_value = str(
            self.get_parameter("transition_system_path").value
        ).strip()

        if self._waiting_for_initial_state:
            if ts_path_value:
                self._load_transition_system_from_path(ts_path_value)

            self.get_logger().info(
                "Waiting for the initial TS state on /ts_state."
            )
        elif ts_path_value:
            self._initialize_planner()
        else:
            self.get_logger().info(
                "Waiting for a transition system on "
                "/load_transition_system."
            )

    def _set_planner_status(self, state: int, message: str) -> None:
        """Store and publish the authoritative planner lifecycle state."""
        valid_states = {
            PlannerStatus.UNINITIALIZED,
            PlannerStatus.READY,
            PlannerStatus.PLANNING,
            PlannerStatus.ACTIVE,
        }

        if state not in valid_states:
            raise ValueError(f"Unsupported planner lifecycle state: {state}")

        with self._state_lock:
            self._planner_state = state
            status = PlannerStatus()
            status.state = state
            status.message = message
            self.planner_status_publisher.publish(status)

    @staticmethod
    def _prepare_transition_system(
        transition_system_yaml: str,
        initial_states_dict=None,
    ) -> tuple[TSModel, str]:
        """Parse and fully construct a TS candidate without activating it."""
        if not transition_system_yaml.strip():
            raise ValueError("Transition-system YAML cannot be empty.")

        ts_data = import_ts_from_file(transition_system_yaml)
        state_models = state_models_from_ts(
            ts_data,
            initial_states_dict=initial_states_dict,
        )
        transition_system = TSModel(state_models)
        transition_system.build_full()

        # The digest identifies the exact UTF-8 YAML payload received.
        active_hash = hashlib.sha256(
            transition_system_yaml.encode("utf-8")
        ).hexdigest()
        return transition_system, active_hash

    def _activate_transition_system(
        self,
        transition_system: TSModel,
        transition_system_yaml: str,
        active_hash: str,
    ) -> None:
        """Atomically replace the active validated transition system."""
        with self._state_lock:
            self._active_transition_system = transition_system
            self._active_ts_yaml = transition_system_yaml
            self._active_ts_sha256 = active_hash
            self.ltl_planner = None
            self._set_planner_status(
                PlannerStatus.READY,
                "Transition system loaded; no active plan.",
            )

    def _load_transition_system_from_path(
        self,
        ts_path_value: str,
        initial_states_dict=None,
    ) -> bool:
        """Load the startup TS path through the shared activation path."""
        ts_path = Path(ts_path_value).expanduser()

        if not ts_path.is_file():
            self.get_logger().error(
                f"Transition-system file does not exist: {ts_path}"
            )
            return False

        try:
            transition_system_yaml = ts_path.read_text(encoding="utf-8")
            transition_system, active_hash = (
                self._prepare_transition_system(
                    transition_system_yaml,
                    initial_states_dict=initial_states_dict,
                )
            )
        except Exception as error:
            self.get_logger().error(
                f"Cannot load transition system from {ts_path}: {error}"
            )
            return False

        self._activate_transition_system(
            transition_system,
            transition_system_yaml,
            active_hash,
        )
        return True

    def _load_transition_system_callback(self, request, response):
        """Validate and atomically activate a transition system from YAML."""
        with self._state_lock:
            if self._planner_state not in {
                PlannerStatus.UNINITIALIZED,
                PlannerStatus.READY,
            }:
                response.success = False
                response.message = (
                    "Transition-system loading is only allowed while "
                    "UNINITIALIZED or READY."
                )
                response.active_ts_sha256 = self._active_ts_sha256
                return response

            try:
                transition_system, active_hash = (
                    self._prepare_transition_system(
                        request.transition_system_yaml
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                self.get_logger().warning(
                    f"Rejected transition-system YAML: {error}"
                )
                response.success = False
                response.message = str(error)
                response.active_ts_sha256 = self._active_ts_sha256
                return response
            except Exception as error:
                self.get_logger().error(
                    "Unexpected transition-system loading failure: "
                    f"{error}"
                )
                response.success = False
                response.message = (
                    "Unexpected transition-system loading failure: "
                    f"{error}"
                )
                response.active_ts_sha256 = self._active_ts_sha256
                return response

            self._activate_transition_system(
                transition_system,
                request.transition_system_yaml,
                active_hash,
            )

            response.success = True
            response.message = "Transition system loaded successfully."
            response.active_ts_sha256 = self._active_ts_sha256
            return response

    def _initialize_plugins(self) -> None:
        """Load configured planner plugins after planning is available."""
        if self._plugins_initialized:
            return

        config_path = self.get_parameter(
            "plugin_config_path"
        ).value

        if not config_path:
            self._plugins_initialized = True
            return

        try:
            plugin_specs = load_plugin_specs(config_path)
        except (OSError, ValueError, yaml.YAMLError) as error:
            self.get_logger().error(
                f"Cannot load planner plugin configuration: {error}"
            )
            return

        loaded_plugins = {}

        for class_name, spec in plugin_specs.items():
            try:
                module = importlib.import_module(spec["path"])
                plugin_class = getattr(module, class_name)
                plugin = plugin_class(
                    self.ltl_planner,
                    spec.get("args", {}),
                )

                if hasattr(plugin, "set_node"):
                    plugin.set_node(self)

                for method_name in (
                    "init",
                    "set_sub_and_pub",
                    "run_at_ts_update",
                ):
                    if not callable(getattr(plugin, method_name, None)):
                        raise TypeError(
                            f"Plugin {class_name!r} does not implement "
                            f"{method_name}()."
                        )

                loaded_plugins[class_name] = plugin
            except (ImportError, AttributeError, TypeError) as error:
                self.get_logger().error(
                    f"Cannot load planner plugin {class_name!r}: {error}"
                )

        for class_name, plugin in loaded_plugins.items():
            try:
                plugin.init()
                plugin.set_sub_and_pub()
            except Exception as error:
                self.get_logger().error(
                    f"Cannot initialize planner plugin "
                    f"{class_name!r}: {error}"
                )
                continue

            self.plugins[class_name] = plugin
            self.get_logger().info(
                f"Initialized planner plugin {class_name!r}."
            )

        self._plugins_initialized = True

    def _run_plugins(self, ts_state) -> None:
        """Run every initialized plugin for an accepted TS update."""
        for class_name, plugin in self.plugins.items():
            try:
                plugin.run_at_ts_update(ts_state)
            except Exception as error:
                self.get_logger().error(
                    f"Planner plugin {class_name!r} failed during "
                    f"a TS update: {error}"
                )

    def _parameter_update_callback(self, parameters):
        """Apply supported runtime planner behavior parameters."""
        updates = {
            parameter.name: parameter.value
            for parameter in parameters
            if parameter.name in {
                "replan_on_unplanned_move",
                "check_timestamp",
            }
        }

        if any(
            not isinstance(value, bool)
            for value in updates.values()
        ):
            return SetParametersResult(
                successful=False,
                reason="Planner behavior parameters must be boolean.",
            )

        if "replan_on_unplanned_move" in updates:
            self.replan_on_unplanned_move = updates[
                "replan_on_unplanned_move"
            ]

        if "check_timestamp" in updates:
            self.check_timestamp = updates["check_timestamp"]

        return SetParametersResult(successful=True)

    def _initialize_planner(
        self,
        initial_states_dict=None,
    ) -> bool:
        """Create the initial plan from the active transition system."""
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

        if self._active_transition_system is None:
            ts_path_value = str(
                self.get_parameter("transition_system_path").value
            ).strip()

            if not ts_path_value:
                self.get_logger().error(
                    "No active transition system is available."
                )
                return False

            if not self._load_transition_system_from_path(
                ts_path_value,
                initial_states_dict=initial_states_dict,
            ):
                return False
        elif initial_states_dict is not None:
            try:
                transition_system, active_hash = (
                    self._prepare_transition_system(
                        self._active_ts_yaml,
                        initial_states_dict=initial_states_dict,
                    )
                )
            except Exception as error:
                self.get_logger().error(
                    "Cannot apply the agent initial TS state: "
                    f"{error}"
                )
                return False

            self._activate_transition_system(
                transition_system,
                self._active_ts_yaml,
                active_hash,
            )

        if not hard_task:
            self.get_logger().error(
                "Parameter 'hard_task' is required."
            )
            return False

        if not soft_task:
            self.get_logger().error(
                "Parameter 'soft_task' is required."
            )
            return False

        with self._state_lock:
            transition_system = self._active_transition_system
            self._set_planner_status(
                PlannerStatus.PLANNING,
                "Initial LTL planning is in progress.",
            )

        try:
            planner = LTLPlanner(
                transition_system,
                hard_task,
                soft_task,
                beta=beta,  # type: ignore
                gamma=gamma,  # type: ignore
            )

            success = planner.optimal(
                style="static"
            )

        except Exception as error:
            self.get_logger().error(
                f"Planner initialization failed: {error}"
            )
            with self._state_lock:
                self.ltl_planner = None
                self._set_planner_status(
                    PlannerStatus.READY,
                    "Initial planning failed; "
                    "transition system remains ready.",
                )
            return False

        if not success or planner.run is None:
            self.get_logger().error(
                "No accepting LTL plan was found."
            )
            with self._state_lock:
                self.ltl_planner = None
                self._set_planner_status(
                    PlannerStatus.READY,
                    "No accepting plan; transition system remains ready.",
                )
            return False

        with self._state_lock:
            self.ltl_planner = planner

        initial_states = (
            self.ltl_planner.product
            .graph["ts"]  # type: ignore
            .graph["initial"]
        )

        if initial_states:
            self.ltl_planner.curr_ts_state = next(
                iter(initial_states)
            )

        self._set_planner_status(
            PlannerStatus.ACTIVE,
            "An accepted LTL run is active.",
        )

        self._publish_possible_states()

        self._initialize_plugins()

        self.get_logger().info(
            "Initial LTL planning succeeded."
        )
        self.get_logger().info(
            f"Prefix actions: {self.ltl_planner.run.pre_plan}"
        )
        self.get_logger().info(
            f"Suffix actions: {self.ltl_planner.run.suf_plan}"
        )

        self._publish_plan()
        self._publish_next_move()
        return True

    def _state_dimension_names(self) -> list[str]:
        """Return flattened TS state-dimension names."""
        if (
            self.ltl_planner is None
            or self.ltl_planner.product is None
        ):
            return []

        raw_names = (
            self.ltl_planner.product
            .graph["ts"]
            .graph.get("ts_state_format", [])
        )

        dimension_names = []

        for name in raw_names:
            if isinstance(name, (list, tuple)):
                dimension_names.extend(
                    str(item)
                    for item in name
                )
            else:
                dimension_names.append(str(name))

        return dimension_names

    def _state_to_message(
        self,
        state,
    ) -> TransitionSystemState:
        """Convert an internal TS node into a ROS2 state message."""
        message = TransitionSystemState()

        if isinstance(state, tuple):
            message.states = [
                str(value)
                for value in state
            ]
        else:
            message.states = [str(state)]

        message.state_dimension_names = (
            self._state_dimension_names()
        )

        return message

    def _publish_plan(self) -> None:
        """Publish the current prefix and suffix plans."""
        if (
            self.ltl_planner is None
            or self.ltl_planner.run is None
        ):
            self.get_logger().warning(
                "No plan is available for publication."
            )
            return

        run = self.ltl_planner.run
        stamp = self.get_clock().now().to_msg()

        prefix_message = LTLPlan()
        prefix_message.header.stamp = stamp
        prefix_message.action_sequence = list(
            run.pre_plan
        )
        prefix_message.ts_state_sequence = [
            self._state_to_message(state)
            for state in run.line
        ]

        suffix_message = LTLPlan()
        suffix_message.header.stamp = stamp
        suffix_message.action_sequence = list(
            run.suf_plan
        )
        suffix_message.ts_state_sequence = [
            self._state_to_message(state)
            for state in run.loop
        ]

        self.prefix_plan_publisher.publish(
            prefix_message
        )
        self.suffix_plan_publisher.publish(
            suffix_message
        )

        self.get_logger().info(
            "Published prefix and suffix plans."
        )

    def _publish_possible_states(self) -> None:
        """Publish currently possible product-automaton states."""
        if (
            self.ltl_planner is None
            or self.ltl_planner.product is None
        ):
            self.get_logger().warning(
                "No product automaton is available."
            )
            return

        possible_states = getattr(
            self.ltl_planner.product,
            "possible_states",
            set(),
        )

        ltl_state_messages: list[LTLState] = []

        for ts_state, buchi_state in sorted(
            possible_states,
            key=str,
        ):
            ltl_state_message = LTLState()
            ltl_state_message.ts_state = (
                self._state_to_message(ts_state)
            )
            ltl_state_message.buchi_state = str(
                buchi_state
            )

            ltl_state_messages.append(
                ltl_state_message
            )

        message = LTLStateArray()
        message.ltl_states = ltl_state_messages

        published_states = [
            (
                list(ltl_state.ts_state.states),
                ltl_state.buchi_state,
            )
            for ltl_state in ltl_state_messages
        ]

        self.get_logger().info(
            f"Publishing possible LTL states: {published_states}"
        )

        self.possible_states_publisher.publish(
            message
        )

        self.get_logger().info(
            f"Published {len(ltl_state_messages)} "
            "possible LTL states."
        )

    def _update_possible_states(
        self,
        ts_state: tuple[str, ...],
    ) -> bool:
        """Update and publish product states matching a TS state."""
        if self.ltl_planner is None:
            self.get_logger().warning(
                "Cannot update possible states before "
                "planner initialization."
            )
            return False

        states_available = (
            self.ltl_planner.update_possible_states(
                ts_state
            )
        )

        if not states_available:
            self.get_logger().warning(
                f"No possible product states were found for "
                f"{ts_state}."
            )

        self._publish_possible_states()
        return states_available

    @staticmethod
    def _message_stamp(message) -> tuple[int, int]:
        """Return a comparable ROS timestamp tuple."""
        return (
            message.header.stamp.sec,
            message.header.stamp.nanosec,
        )

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

    def _task_replanning_callback(
        self,
        request,
        response,
    ):
        """Replan from the current TS state using a new LTL task."""
        if (
            self.ltl_planner is None
            or self.ltl_planner.curr_ts_state is None
        ):
            self.get_logger().error(
                "Cannot replan before planner initialization."
            )
            response.success = False
            return response

        hard_task = request.hard_task.strip()
        soft_task = request.soft_task.strip()

        if not hard_task:
            self.get_logger().error(
                "Replanning request contains an empty hard task."
            )
            response.success = False
            return response

        if not soft_task:
            self.get_logger().error(
                "Replanning request contains an empty soft task."
            )
            response.success = False
            return response

        current_state = self.ltl_planner.curr_ts_state

        self._set_planner_status(
            PlannerStatus.PLANNING,
            "Task replanning is in progress.",
        )

        self.get_logger().info(
            "Received task replanning request."
        )
        self.get_logger().info(
            f"New hard task: {hard_task}"
        )
        self.get_logger().info(
            f"New soft task: {soft_task}"
        )
        self.get_logger().info(
            f"Replanning from TS state: {current_state}"
        )

        try:
            replanned = self.ltl_planner.replan_task(
                hard_task,
                soft_task,
                current_state,
            )
        except Exception as error:
            self.get_logger().error(
                f"Task replanning failed: {error}"
            )
            self._set_planner_status(
                PlannerStatus.ACTIVE,
                "Task replanning failed; the previous run remains active.",
            )
            response.success = False
            return response

        if (
            not replanned
            or self.ltl_planner.run is None
            or self.ltl_planner.next_move is None
        ):
            self.get_logger().error(
                "No accepting plan was found for the new task."
            )
            self._set_planner_status(
                PlannerStatus.ACTIVE,
                "Task replanning failed; the previous run remains active.",
            )
            response.success = False
            return response

        self._set_planner_status(
            PlannerStatus.ACTIVE,
            "The replanned accepted LTL run is active.",
        )

        self._publish_possible_states()
        self._publish_plan()
        self._publish_next_move()

        self.get_logger().info(
            "Task replanning succeeded."
        )

        response.success = True
        return response

    def _ts_state_callback(self, message):
        """Advance the plan when the expected TS state is reached."""
        if self._waiting_for_initial_state:
            try:
                initial_states = initial_states_from_message(
                    message
                )
            except ValueError as error:
                self.get_logger().error(str(error))
                return

            if self._initialize_planner(initial_states):
                self._waiting_for_initial_state = False
                self._previous_state_stamp = self._message_stamp(
                    message
                )
                self.get_logger().info(
                    "Initialized the planner from the agent TS state."
                )

            return

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

        message_stamp = self._message_stamp(message)

        if (
            self.check_timestamp
            and message_stamp == self._previous_state_stamp
        ):
            self.get_logger().warning(
                "Ignoring TS state with a repeated timestamp: "
                f"{message_stamp}."
            )
            return

        self._previous_state_stamp = message_stamp

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

            if not self.replan_on_unplanned_move:
                self.ltl_planner.curr_ts_state = reached_state

                if self._update_possible_states(reached_state):
                    self._run_plugins(reached_state)
                    self.get_logger().warning(
                        "Automatic replanning for an unplanned move "
                        "is disabled; keeping the current plan cursor."
                    )
                    return

                self.get_logger().warning(
                    "The unplanned state invalidated all possible "
                    "Product states; replanning is required."
                )

            try:
                self._set_planner_status(
                    PlannerStatus.PLANNING,
                    "State-based replanning is in progress.",
                )
                replanned = self.ltl_planner.replan_from_ts_state(
                    reached_state
                )
            except Exception as error:
                self.get_logger().error(
                    f"Replanning from {reached_state} failed: {error}"
                )
                self._set_planner_status(
                    PlannerStatus.ACTIVE,
                    "State-based replanning failed; "
                    "the previous run remains active.",
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
                self._set_planner_status(
                    PlannerStatus.ACTIVE,
                    "State-based replanning failed; "
                    "the previous run remains active.",
                )
                return

            self.ltl_planner.curr_ts_state = reached_state

            self._set_planner_status(
                PlannerStatus.ACTIVE,
                "The state-replanned accepted LTL run is active.",
            )

            self._publish_possible_states()

            self.get_logger().info(
                f"Replanning succeeded from {reached_state}."
            )
            self.get_logger().info(
                f"Selected next move: {self.ltl_planner.next_move}"
            )

            self._publish_plan()
            self._publish_next_move()
            self._run_plugins(reached_state)
            return

        self.ltl_planner.curr_ts_state = reached_state

        self._update_possible_states(
            reached_state
        )

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

        self._publish_plan()
        self._publish_next_move()
        self._run_plugins(reached_state)

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

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
