"""Resolve formal observations against one retained accepted run."""

from itertools import chain, islice

from ltl_automaton_execution.models import ExecutionStep


class ResolutionError(ValueError):
    """The public snapshot cannot resolve one unambiguous execution step."""


class AcceptedRunResolver:
    """Resolve only edges explicitly retained by the accepted run."""

    def __init__(self):
        self._indexed_snapshot = None
        self._nodes = {}
        self._retained_targets = {}

    def resolve(self, observation, snapshot):
        """Return one exact symbolic step or fail closed."""
        self._validate_identity(observation, snapshot)
        if not observation.has_next_action or not observation.next_action:
            raise ResolutionError("Observation has no executable next action.")

        nodes, retained_targets = self._snapshot_index(snapshot)
        current_ids = tuple(sorted(set(observation.possible_product_node_ids)))
        if not current_ids:
            raise ResolutionError("Observation has no possible Product nodes.")
        missing = [node_id for node_id in current_ids if node_id not in nodes]
        if missing:
            raise ResolutionError(
                f"Observation references missing Product nodes: {missing}."
            )

        source_state = nodes[current_ids[0]].ts_state
        if any(
            nodes[node_id].ts_state != source_state for node_id in current_ids
        ):
            raise ResolutionError(
                "Possible Product nodes represent distinct symbolic TS states."
            )

        source_product_node_ids = set()
        target_product_node_ids = set()
        target_state = None
        ambiguous_target = False
        for source_id in current_ids:
            for target_id in retained_targets.get(
                (source_id, observation.next_action), ()
            ):
                candidate_state = nodes[target_id].ts_state
                if not target_product_node_ids:
                    target_state = candidate_state
                elif candidate_state != target_state:
                    ambiguous_target = True
                source_product_node_ids.add(source_id)
                target_product_node_ids.add(target_id)

        if not target_product_node_ids:
            raise ResolutionError(
                "Next action is not represented from the current accepted-run state."
            )
        if ambiguous_target:
            raise ResolutionError(
                "Accepted-run candidates have ambiguous symbolic targets."
            )

        return ExecutionStep(
            planner_instance_id=observation.planner_instance_id,
            planning_generation=observation.planning_generation,
            execution_step_seq=observation.execution_step_seq,
            action=observation.next_action,
            source_state=source_state,
            target_state=target_state,
            source_product_node_ids=tuple(sorted(source_product_node_ids)),
            target_product_node_ids=tuple(sorted(target_product_node_ids)),
        )

    def _snapshot_index(self, snapshot):
        """Index one immutable snapshot, replacing rather than accumulating graphs."""
        if snapshot is self._indexed_snapshot:
            return self._nodes, self._retained_targets

        nodes = self._node_map(snapshot)
        ordered_pairs = self._retained_pairs(snapshot)
        retained_pairs = set(ordered_pairs)
        matched_pairs = set()
        retained_edges = []

        for edge in snapshot.product_edges:
            pair = (edge.source_id, edge.target_id)
            if pair in retained_pairs:
                matched_pairs.add(pair)
                retained_edges.append(edge)

        missing = [
            pair for pair in ordered_pairs if pair not in matched_pairs
        ]
        if missing:
            raise ResolutionError(
                f"Accepted run references missing Product edges: {missing}."
            )

        retained_nodes = {
            node_id for pair in retained_pairs for node_id in pair
        }
        missing = sorted(retained_nodes - nodes.keys())
        if missing:
            raise ResolutionError(
                f"Accepted run references missing Product nodes: {missing}."
            )

        targets = {}
        for edge in retained_edges:
            targets.setdefault(
                (edge.source_id, edge.action), set()
            ).add(edge.target_id)

        # PlanningSnapshot and its nested models are frozen. Object identity
        # prevents accidentally reusing indexes for a newly received graph.
        self._indexed_snapshot = snapshot
        self._nodes = nodes
        self._retained_targets = targets
        return nodes, targets

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
        if len(suffix) > 1 and suffix[-1] == suffix[0]:
            raise ResolutionError(
                "Accepted suffix repeats its start node at the end."
            )
        return tuple(chain(
            zip(prefix, islice(prefix, 1, None)),
            zip(suffix, islice(suffix, 1, None)),
            ((suffix[-1], suffix[0]),),
        ))
