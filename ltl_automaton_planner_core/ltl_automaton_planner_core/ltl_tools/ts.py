# -*- coding: utf-8 -*-
import logging
from copy import copy
from itertools import product as cartesian_product

from networkx.classes.digraph import DiGraph

from ..boolean_formulas.parser import parse as parse_guard


_LOGGER = logging.getLogger(__name__)


class TSModel(DiGraph):

    def __init__(self, state_models):
        """TS model, built from a list of state models to combine."""
        if not state_models:
            raise ValueError("At least one state model is required.")
        DiGraph.__init__(self, initial=set(), ts_state_format=[])
        self.state_models = state_models
        self._guard_cache = {}

    def build_full(self):
        """Build TS graph from one or more state model TS."""
        self._guard_cache.clear()
        # If only one state model, use directly as the TS
        if len(self.state_models) == 1:
            DiGraph.__init__(self,
                             incoming_graph_data=self.state_models[0],
                             initial=copy(self.state_models[0].graph['initial']),
                             ts_state_format=self.state_models[0].graph['ts_state_format'])
            disallowed = [
                (source, target) for source, target, data in self.edges(data=True)
                if not self.is_action_allowed(
                    data['guard'], self.nodes[source].get('label', source)
                )
            ]
            self.remove_edges_from(disallowed)

        # If more than one, build a combined TS model
        else:
            # Build digraph object
            DiGraph.__init__(self,
                             initial=set(),
                             ts_state_format=[
                                 model.graph['ts_state_format'] for model in self.state_models]
                             )
            # Compose and add nodes
            self.compose_nodes(self.state_models)
            # Compose and add edges between nodes
            self.compose_edges(self.state_models)
            # Compose initial state
            self.compose_initial(self.state_models)

        _LOGGER.info(
            "Full TS model constructed with %d states and %d transitions.",
            self.number_of_nodes(),
            self.number_of_edges()
        )

        _LOGGER.info(
            "Initial state in TS is: %s",
            self.graph['initial']
        )

    def set_initial(self, ts_state):
        """Delete and set new initial state."""
        # If state exist in graph, change initial and return true
        if ts_state in self.nodes():
            self.graph['initial'] = set([ts_state])
            return True
        # If state doesn't exist in graph, return false
        else:
            return False

    def compose_initial(self, graph_list):
        """
        Compose and set initial state.

        Create products of initial nodes from the input graph list.

        """
        initial_states = [list(graph.graph['initial']) for graph in graph_list]
        self.graph['initial'].update(
            self._iter_node_product(*initial_states)
        )

    def compose_nodes(self, graph_list):
        """
        Compose and add nodes to the digraph.

        Nodes are products of nodes from the input graph list.
        """
        for node in self._iter_node_product(*graph_list):
            self.add_node(node, label=node, marker='unvisited')

    def compose_edges(self, graph_list):
        """
        Compose and add edges to the digraph.

        Nodes are products of nodes from the input graph list.

        Needs to be called after composing nodes.
        """
        # Enumerate each combined source node once, then expand only the
        # actual successors of each factor state.  Keeping factors in order
        # preserves the historical later-dimension overwrite for collisions.
        successor_tables = [{} for _ in graph_list]
        for node in self.nodes:
            guard_checks = {}
            for i, graph in enumerate(graph_list):
                state = (node[i],)
                state_successors = successor_tables[i].get(state)
                if state_successors is None:
                    state_successors = tuple(
                        (
                            successor_state,
                            graph[state][successor_state],
                        )
                        for successor_state in graph.successors(state)
                    )
                    successor_tables[i][state] = state_successors
                for successor_state, edge_data in state_successors:
                    guard = edge_data['guard']
                    if guard not in guard_checks:
                        guard_checks[guard] = self.is_action_allowed(
                            guard,
                            self.nodes[node]['label'],
                        )
                    if not guard_checks[guard]:
                        continue

                    successor_state_node = list(node)
                    successor_state_node[i] = successor_state[0]
                    successor_node = tuple(successor_state_node)
                    self.add_edge(
                        node,
                        successor_node,
                        action=edge_data['action'],
                        guard=edge_data['guard'],
                        weight=edge_data['weight'],
                        marker='visited',
                    )

    def is_action_allowed(self, action_guard, ts_label):
        """Check action guard against the node label."""
        if action_guard not in self._guard_cache:
            self._guard_cache[action_guard] = parse_guard(action_guard)
        return self._guard_cache[action_guard].check(ts_label)

    @staticmethod
    def _iter_node_product(*args):
        """Yield flattened product nodes without materializing the product."""
        for combination in cartesian_product(*args):
            yield tuple(
                value
                for node in combination
                for value in node
            )

    @staticmethod
    def node_product(*args):
        """
        Return a list of product nodes.

        Take as input lists of nodes.

        """
        return list(TSModel._iter_node_product(*args))
