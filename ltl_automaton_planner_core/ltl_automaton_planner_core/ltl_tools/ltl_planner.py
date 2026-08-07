"""Coordinate LTL planning over a transition system."""

from copy import deepcopy
import logging

from .buchi import mission_to_buchi
from .discrete_plan import (
    dijkstra_plan_networkX,
    improve_plan_given_history,
)
from .product import ProdAut


_LOGGER = logging.getLogger(__name__)


class LTLPlanner:
    """Coordinate product construction, planning, and plan execution state."""

    def __init__(
        self,
        ts,
        hard_spec,
        soft_spec,
        beta=1000,
        gamma=10,
    ):
        """Initialize the planner from a TS and hard/soft LTL tasks."""
        self.hard_spec = hard_spec
        self.soft_spec = soft_spec
        self.ts = ts

        self.product = None
        self.run = None
        self.planning_time = None

        self.Time = 0
        self.curr_ts_state: tuple[str, ...] | None = None
        self.trace = []
        self.traj = []
        self.opt_log = []
        self.com_log = []

        self.beta = beta
        self.gamma = gamma

        self.last_time = 0
        self.acc_change = 0
        self.index = 0
        self.segment = "line"
        self.next_move = None

    def optimal(self, style="static"):
        """Construct or update the product and compute an accepting run."""
        _LOGGER.info(
            "LTL Planner: --- Planning in progress (%s) ---",
            style,
        )
        _LOGGER.info(
            "LTL Planner: Hard task is: %s",
            self.hard_spec,
        )
        _LOGGER.info(
            "LTL Planner: Soft task is: %s",
            self.soft_spec,
        )

        if style == "static":
            buchi = mission_to_buchi(
                self.hard_spec,
                self.soft_spec,
            )
            self.product = ProdAut(
                self.ts,
                buchi,
                self.beta,
            )

            self.product.graph["ts"].build_full()
            self.product.build_full()

        elif style == "ready":
            if self.product is None:
                _LOGGER.error(
                    'LTL Planner: "ready" planning was requested, '
                    "but the product graph was never built."
                )
                return False

            self.product.build_full()

        elif style == "on-the-fly-initial":
            if self.product is None:
                _LOGGER.error(
                    'LTL Planner: "on-the-fly-initial" planning was '
                    "requested, but the product graph was never built."
                )
                return False

            self.product.build_initial()
            self.product.build_accept()

        elif style == "on-the-fly-task":
            if self.product is None:
                _LOGGER.error(
                    'LTL Planner: "on-the-fly-task" planning was '
                    "requested, but the product graph was never built."
                )
                return False

            buchi = mission_to_buchi(
                self.hard_spec,
                self.soft_spec,
            )

            # Rebuild the product instead of retaining nodes and edges that
            # belong to the previous Büchi automaton.
            self.product = ProdAut(
                self.ts,
                buchi,
                self.beta,
            )
            self.product.build_full()

        else:
            _LOGGER.error(
                "LTL Planner: Unsupported planning style: %s",
                style,
            )
            return False

        self.run, self.planning_time = dijkstra_plan_networkX(
            self.product,
            self.gamma,
        )

        if self.run is None:
            _LOGGER.error(
                "LTL Planner: No valid plan was found. "
                "Check the transition system and LTL task."
            )
            return False

        if not self._initialize_execution_state():
            return False

        _LOGGER.info(
            "LTL Planner: --- Planning successful! ---"
        )
        _LOGGER.debug(
            "Prefix states: %s",
            self.run.line,
        )
        _LOGGER.debug(
            "Suffix states: %s",
            self.run.loop,
        )

        self.opt_log.append(
            (
                self.Time,
                self.run.pre_plan,
                self.run.suf_plan,
                self.run.precost,
                self.run.sufcost,
                self.run.totalcost,
            )
        )
        self.last_time = self.Time
        self.acc_change = 0

        return True

    def _initialize_execution_state(self):
        """Initialize the execution cursor from the current accepting run."""
        if self.run is None:
            self.next_move = None
            return False

        self.index = 0

        if self.run.pre_plan:
            self.segment = "line"
            self.next_move = self.run.pre_plan[0]
            return True

        if self.run.suf_plan:
            self.segment = "loop"
            self.next_move = self.run.suf_plan[0]
            return True

        self.next_move = None
        _LOGGER.error(
            "LTL Planner: The accepting run contains no executable actions."
        )
        return False

    def update_possible_states(self, ts_node):
        """Update possible product states after observing a TS state."""
        if self.product is None:
            _LOGGER.error(
                "LTL Planner: Cannot update states before building a product."
            )
            return False

        self.product.possible_states = (
            self.product.get_possible_states(ts_node)
        )

        if self._reaches_accepting_boundary():
            self.product.possible_states = self.intersect_accept(
                self.product.possible_states,
                ts_node,
            )

        return bool(self.product.possible_states)

    def intersect_accept(self, possible_states, reach_ts):
        """Keep possible states that are accepting at the reached TS state."""
        if self.product is None:
            return set()

        accept_set = self.product.graph["accept"]

        return {
            state
            for state in possible_states
            if state in accept_set and state[0] == reach_ts
        }

    def _reaches_accepting_boundary(self):
        """Return whether the latest move reaches an accepting boundary."""
        if self.run is None:
            return False

        if self.segment == "line":
            return (
                bool(self.run.pre_plan)
                and self.index == len(self.run.pre_plan) - 1
            )

        if self.segment == "loop":
            return (
                bool(self.run.suf_plan)
                and self.index == len(self.run.suf_plan) - 1
            )

        return False

    def find_next_move(self):
        """Advance the execution cursor and return the next planned action."""
        if self.run is None or self.next_move is None:
            raise RuntimeError(
                "No executable plan is currently available."
            )

        if self.segment == "line":
            if not self.run.pre_plan:
                raise RuntimeError(
                    "Planner is in the prefix segment, but prefix is empty."
                )

            self.trace.append(
                self.run.line[self.index]
            )

            if self.index < len(self.run.pre_plan) - 1:
                self.index += 1
                self.next_move = self.run.pre_plan[self.index]
            else:
                if not self.run.suf_plan:
                    raise RuntimeError(
                        "The accepting run has no suffix action."
                    )

                self.index = 0
                self.segment = "loop"
                self.next_move = self.run.suf_plan[0]

        elif self.segment == "loop":
            if not self.run.suf_plan:
                raise RuntimeError(
                    "Planner is in the suffix segment, but suffix is empty."
                )

            self.trace.append(
                self.run.loop[self.index]
            )
            self.index = (
                self.index + 1
            ) % len(self.run.suf_plan)
            self.next_move = self.run.suf_plan[self.index]

        else:
            raise RuntimeError(
                f"Unknown execution segment: {self.segment}"
            )

        return self.next_move

    def replan_from_ts_state(self, ts_state):
        """Replan after replacing the current TS initial state."""
        snapshot = deepcopy(self.__dict__)
        target_ts = (
            self.ts
            if self.product is None
            else self.product.graph["ts"]
        )

        if not target_ts.set_initial(ts_state):
            _LOGGER.error(
                "LTL Planner: Cannot replan from unknown TS state %s.",
                ts_state,
            )
            return False

        try:
            replanned = self.optimal(
                style=(
                    "static"
                    if self.product is None
                    else "on-the-fly-initial"
                )
            )
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(snapshot)
            raise

        if not replanned:
            self.__dict__.clear()
            self.__dict__.update(snapshot)

        return replanned

    def replan_task(
        self,
        hard_spec,
        soft_spec,
        initial_ts_state=None,
    ):
        """Replace the task and optionally the current TS initial state."""
        snapshot = deepcopy(self.__dict__)
        target_ts = (
            self.ts
            if self.product is None
            else self.product.graph["ts"]
        )

        if initial_ts_state is not None:
            if not target_ts.set_initial(initial_ts_state):
                _LOGGER.error(
                    "LTL Planner: Cannot replan task from unknown "
                    "TS state %s.",
                    initial_ts_state,
                )
                return False

        self.hard_spec = hard_spec
        self.soft_spec = soft_spec

        try:
            replanned = self.optimal(
                style=(
                    "static"
                    if self.product is None
                    else "on-the-fly-task"
                )
            )
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(snapshot)
            raise

        if not replanned:
            self.__dict__.clear()
            self.__dict__.update(snapshot)

        return replanned

    def replan(self):
        """Create a new plan consistent with the execution history."""
        if self.product is None or self.run is None:
            _LOGGER.error(
                "LTL Planner: Cannot replan before an initial plan exists."
            )
            return False

        new_run = improve_plan_given_history(
            self.product,
            self.trace,
        )

        if new_run is None:
            _LOGGER.error(
                "LTL Planner: Replanning did not find an accepting run."
            )
            return False

        _LOGGER.debug(
            "Replanned prefix states: %s",
            new_run.line,
        )
        _LOGGER.debug(
            "Replanned suffix states: %s",
            new_run.loop,
        )

        remaining_prefix = (
            self.run.pre_plan[self.index:]
            if self.segment == "line"
            else []
        )

        if (
            new_run.pre_plan == remaining_prefix
            and new_run.suf_plan == self.run.suf_plan
        ):
            _LOGGER.info(
                "LTL Planner: The current plan remains valid."
            )
            return False

        self.run = new_run

        if not self._initialize_execution_state():
            return False

        _LOGGER.info(
            "LTL Planner: Plan adapted."
        )
        return True
