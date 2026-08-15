"""ROS-independent immutable execution models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolicState:
    """Ordered transition-system dimensions and their values."""

    dimension_names: tuple[str, ...]
    states: tuple[str, ...]

    def __post_init__(self):
        if not self.dimension_names or len(self.dimension_names) != len(self.states):
            raise ValueError("Symbolic state dimensions and values must align.")
        if any(not name or not name.strip() for name in self.dimension_names):
            raise ValueError("Symbolic state dimensions must be non-empty.")
        if len(set(self.dimension_names)) != len(self.dimension_names):
            raise ValueError("Symbolic state dimensions must be unique.")
        if any(not value or not value.strip() for value in self.states):
            raise ValueError("Symbolic state values must be non-empty.")


@dataclass(frozen=True)
class ProductNode:
    """Snapshot-local Product node reduced to its symbolic TS state."""

    node_id: int
    ts_state: SymbolicState


@dataclass(frozen=True)
class ProductEdge:
    """Snapshot-local directed Product edge and its formal action."""

    source_id: int
    target_id: int
    action: str


@dataclass(frozen=True)
class AcceptedRun:
    """Retained prefix and non-repeated cyclic suffix node sequences."""

    prefix_node_ids: tuple[int, ...]
    suffix_node_ids: tuple[int, ...]


@dataclass(frozen=True)
class PlanningSnapshot:
    """Execution-relevant projection of a public planning graph snapshot."""

    planner_instance_id: str
    planning_generation: int
    product_nodes: tuple[ProductNode, ...]
    product_edges: tuple[ProductEdge, ...]
    accepted_run: AcceptedRun


@dataclass(frozen=True)
class ExecutionObservation:
    """Execution authority projected from PlanningExecutionObservation."""

    planner_instance_id: str
    planning_generation: int
    possible_product_node_ids: tuple[int, ...]
    has_next_action: bool
    next_action: str


@dataclass(frozen=True)
class ExecutionStep:
    """One simulator-independent symbolic action dispatch."""

    planner_instance_id: str
    planning_generation: int
    action: str
    source_state: SymbolicState
    target_state: SymbolicState
    source_product_node_ids: tuple[int, ...]
    target_product_node_ids: tuple[int, ...]


@dataclass(frozen=True)
class ExecutionCompletion:
    """Execution-level backend completion without state authority."""

    success: bool
    message: str
