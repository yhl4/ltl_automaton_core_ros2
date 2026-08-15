"""Resolve formal observations against one retained accepted run."""

from ltl_automaton_execution.models import ExecutionObservation
from ltl_automaton_execution.models import ExecutionStep
from ltl_automaton_execution.models import PlanningSnapshot


class ResolutionError(ValueError):
    """The public snapshot cannot resolve one unambiguous execution step."""


class AcceptedRunResolver:
    """Resolve only edges explicitly retained by the accepted run."""

    def resolve(self, observation, snapshot):
        """Return one exact symbolic step or fail closed."""
        self._validate_identity(observation, snapshot)
        if not observation.has_next_action or not observation.next_action:
            raise ResolutionError("Observation has no executable next action.")

        nodes = self._node_map(snapshot)
        current_ids = tuple(sorted(set(observation.possible_product_node_ids)))
        if not current_ids:
            raise ResolutionError("Observation has no possible Product nodes.")
        missing = [node_id for node_id in current_ids if node_id not in nodes]
        if missing:
            raise ResolutionError(
                f"Observation references missing Product nodes: {missing}."
            )

        source_states = {nodes[node_id].ts_state for node_id in current_ids}
        if len(source_states) != 1:
            raise ResolutionError(
                "Possible Product nodes represent distinct symbolic TS states."
            )
        source_state = next(iter(source_states))

        retained_pairs = self._retained_pairs(snapshot)
        edges = {
            (edge.source_id, edge.target_id, edge.action): edge
            for edge in snapshot.product_edges
        }
        candidates = []
        for source_id, target_id in retained_pairs:
            edge = edges.get((source_id, target_id, observation.next_action))
            if source_id in current_ids and edge is not None:
                candidates.append((source_id, target_id))

        if not candidates:
            raise ResolutionError(
                "Next action is not represented from the current accepted-run state."
            )
        target_states = {nodes[target_id].ts_state for _, target_id in candidates}
        if len(target_states) != 1:
            raise ResolutionError(
                "Accepted-run candidates have ambiguous symbolic targets."
            )

        return ExecutionStep(
            planner_instance_id=observation.planner_instance_id,
            planning_generation=observation.planning_generation,
            action=observation.next_action,
            source_state=source_state,
            target_state=next(iter(target_states)),
            source_product_node_ids=tuple(
                sorted({source_id for source_id, _ in candidates})
            ),
            target_product_node_ids=tuple(
                sorted({target_id for _, target_id in candidates})
            ),
        )

    @staticmethod
    def _validate_identity(observation, snapshot):
        observed = (
            observation.planner_instance_id,
            observation.planning_generation,
        )
        retained = (
            snapshot.planner_instance_id,
            snapshot.planning_generation,
        )
        if observed != retained:
            raise ResolutionError(
                f"Snapshot identity {retained} does not match observation {observed}."
            )

    @staticmethod
    def _node_map(snapshot):
        nodes = {node.node_id: node for node in snapshot.product_nodes}
        if len(nodes) != len(snapshot.product_nodes):
            raise ResolutionError("Snapshot contains duplicate Product node IDs.")
        return nodes

    @staticmethod
    def _retained_pairs(snapshot):
        prefix = snapshot.accepted_run.prefix_node_ids
        suffix = snapshot.accepted_run.suffix_node_ids
        if not prefix:
            raise ResolutionError("Accepted run has no prefix nodes.")
        if not suffix:
            raise ResolutionError("Accepted run has no suffix nodes.")
        if prefix[-1] != suffix[0]:
            raise ResolutionError(
                "Accepted prefix and suffix do not share their boundary node."
            )
        pairs = list(zip(prefix, prefix[1:]))
        pairs.extend(zip(suffix, suffix[1:]))
        pairs.append((suffix[-1], suffix[0]))
        available = {
            (edge.source_id, edge.target_id)
            for edge in snapshot.product_edges
        }
        missing = [pair for pair in pairs if pair not in available]
        if missing:
            raise ResolutionError(
                f"Accepted run references missing Product edges: {missing}."
            )
        return tuple(pairs)
