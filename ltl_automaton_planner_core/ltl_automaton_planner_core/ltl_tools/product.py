# -*- coding: utf-8 -*-
"""Construct and represent TS–Büchi product automata."""

import logging
from itertools import islice

from networkx import strongly_connected_components
from networkx.classes.digraph import DiGraph

from .buchi import check_label_for_buchi_edge
from .ts import TSModel

_LOGGER = logging.getLogger(__name__)


class ProdAut(DiGraph):
    def __init__(self, ts, buchi, beta=1000):
        DiGraph.__init__(
            self,
            ts=ts,
            buchi=buchi,
            beta=beta,
            initial=set(),
            accept=set(),
            accept_with_cycle=set(),
            type='ProdAut')

    # Build product automaton of TS and büchi by exploring every node
    # combination and adding edges when required
    def build_full(self):
        """Rebuild the full product using source-state label semantics."""
        ts = self.graph['ts']
        buchi = self.graph['buchi']
        self.remove_nodes_from(list(self.nodes))
        self.graph['initial'] = set()
        self.graph['accept'] = set()
        guard_keys = {
            (source, target): tuple(
                id(data.get(name))
                for name in ('guard', 'hardguard', 'softguard')
            )
            for source, target, data in buchi.edges(data=True)
        }

        def successor_edges(source):
            source_edges = None
            for target in ts.successors(source):
                if source_edges is None:
                    source_edges = ts[source]
                yield target, source_edges[target]

        for f_ts_node in ts:
            label = ts.nodes[f_ts_node]['label']
            label_checks = {}
            ts_successors = tuple(successor_edges(f_ts_node))
            for f_buchi_node in buchi:
                f_prod_node = self.composition(f_ts_node, f_buchi_node)
                # A Büchi guard depends on the source label, not the TS successor.
                allowed = []
                for t_buchi_node in buchi.successors(f_buchi_node):
                    guard_key = guard_keys[
                        (f_buchi_node, t_buchi_node)
                    ]
                    if guard_key not in label_checks:
                        label_checks[guard_key] = (
                            check_label_for_buchi_edge(
                                buchi,
                                label,
                                f_buchi_node,
                                t_buchi_node,
                            )
                        )
                    truth, dist = label_checks[guard_key]
                    if truth:
                        allowed.append((t_buchi_node, dist))
                for t_ts_node, edge in ts_successors:
                    cost = edge['weight']
                    for t_buchi_node, dist in allowed:
                        t_prod_node = self.composition(t_ts_node, t_buchi_node)
                        total_weight = cost + self.graph['beta'] * dist
                        self.add_edge(
                            f_prod_node,
                            t_prod_node,
                            transition_cost=cost,
                            soft_task_dist=dist,
                            weight=total_weight,
                            action=edge['action'])

        self.build_accept_with_cycle()

        # Build initial possible state set from initial state
        self.possible_states = set(self.graph['initial'])

        _LOGGER.info(
            'LTL Planner: full product constructed with %d states and %s transitions',
            self.number_of_nodes(),
            self.number_of_edges(),
        )

    # Build required for IRL
    def build_full_margin(self, opt_path):
        """Build margin weights from alternating source/target entries."""
        opt_edges = None
        if len(opt_path) >= 2:
            opt_edges = tuple(zip(opt_path[0::2], opt_path[1::2]))
        for f_ts_node in self.graph['ts'].nodes():
            for f_buchi_node in self.graph['buchi'].nodes():
                f_prod_node = self.composition(f_ts_node, f_buchi_node)

                for t_ts_node in self.graph['ts'].successors(f_ts_node):
                    for t_buchi_node in self.graph['buchi'].successors(f_buchi_node):
                        t_prod_node = self.composition(t_ts_node, t_buchi_node)

                        label = self.graph['ts'].nodes[f_ts_node]['label']
                        cost = self.graph['ts'][f_ts_node][t_ts_node]['weight']  # action weight
                        truth, dist = check_label_for_buchi_edge(
                            self.graph['buchi'], label, f_buchi_node, t_buchi_node)
                        total_weight = cost + self.graph['beta'] * dist + 1

                        if opt_edges is not None:
                            if (f_prod_node, t_prod_node) in opt_edges:
                                k = 1
                            else:
                                k = 0
                        else:
                            k = 0
                        total_weight -= k
                        if truth:
                            self.add_edge(
                                f_prod_node,
                                t_prod_node,
                                weight=total_weight,
                                transition_cost=cost,
                                soft_task_dist=dist)

        self.build_accept_with_cycle()

    def update_beta(self, beta):
        """Update edge weights for the supplied soft-task coefficient."""
        self.graph['beta'] = beta

        for _, _, data in self.edges(data=True):
            data['weight'] = data['transition_cost'] + \
                beta * data['soft_task_dist']

    def composition(self, ts_node, buchi_node):
        # Compose node from TS and Büchi
        prod_node = (ts_node, buchi_node)
        # If node not already in product graph, add node to graph
        if not self.has_node(prod_node):
            self.add_node(prod_node, ts=ts_node, buchi=buchi_node, marker='unvisited')
            # If TS and Büchi nodes are both initial nodes in their own graph,
            # composed node is initial
            if ((ts_node in self.graph['ts'].graph['initial']) and
                    (buchi_node in self.graph['buchi'].graph['initial'])):
                self.graph['initial'].add(prod_node)
            # If Büchi node is an accept state, composed node is an accept state
            if (buchi_node in self.graph['buchi'].graph['accept']):
                self.graph['accept'].add(prod_node)
        return prod_node

    def projection(self, prod_node):
        ts_node = self.nodes[prod_node]['ts']
        buchi_node = self.nodes[prod_node]['buchi']
        return ts_node, buchi_node

    # ------------------------------
    # Build initial product states
    # ------------------------------
    # Initial states of TS and Büchi needs to be
    # defined before calling this function
    def build_initial(self):
        # Reset initial set
        self.graph['initial'] = set()
        # Go through all initial states in TS
        for ts_init in self.graph['ts'].graph['initial']:
            # Go through all initial states in Büchi
            for buchi_init in self.graph['buchi'].graph['initial']:
                # If both TS and Büchi state are initial state, build composed node and
                # add it to the product initial set
                init_prod_node = (ts_init, buchi_init)
                self.graph['initial'].add(init_prod_node)

        # Build initial reachable set from initial state
        self.possible_states = set(self.graph['initial'])

    # -----------------------------
    # Build accept product states
    # -----------------------------
    # TS needs to be built and Büchi accept states
    # defined before calling this function
    def build_accept(self):
        # Reset initial set
        self.graph['accept'] = set()
        # Go through all TS states
        for ts_node in self.graph['ts'].nodes():
            # Go through all accept states in Büchi
            for buchi_accept in self.graph['buchi'].graph['accept']:
                accept_prod_node = (ts_node, buchi_accept)
                # If Büchi state is an accept state, build composed node and add it to the
                # product accept set
                self.graph['accept'].add(accept_prod_node)

    # ----------------------------------------
    # Build accept product states with cycle
    # ----------------------------------------
    # TS needs to be built and Büchi accept states
    # defined before calling this function
    def build_accept_with_cycle(self):
        """Find accepting states on a cycle in one SCC traversal."""
        accepting_cycles = set()
        if self.graph.get('accept') == accepting_cycles:
            self.graph['accept_with_cycle'] = accepting_cycles
            return
        for component in strongly_connected_components(self):
            if len(component) > 1 or any(
                self.has_edge(state, state) for state in component
            ):
                accepting_cycles.update(component & self.graph['accept'])
        self.graph['accept_with_cycle'] = accepting_cycles

    def accept_predecessors(self, accept_node):
        pre_set = set()
        t_ts_node, t_buchi_node = self.projection(accept_node)
        for f_ts_node, cost in self.graph['ts'].fly_predecessors(t_ts_node):
            for f_buchi_node in self.graph['buchi'].predecessors(t_buchi_node):
                f_prod_node = self.composition(f_ts_node, f_buchi_node)
                label = self.graph['ts'].nodes[f_ts_node]['label']
                truth, dist = check_label_for_buchi_edge(
                    self.graph['buchi'], label, f_buchi_node, t_buchi_node)
                total_weight = cost + self.graph['beta'] * dist
                if truth:
                    pre_set.add(f_prod_node)
                    self.add_edge(f_prod_node, accept_node, weight=total_weight)
        return pre_set

    def fly_successors(self, f_prod_node):
        """Generate reachable product successors dynamically."""
        f_ts_node, f_buchi_node = self.projection(f_prod_node)

        # Extract nested attributes into readable local variables.
        prod_node_data = self.nodes[f_prod_node]
        ts_node = prod_node_data["ts"]

        region_name = self.graph["ts"].nodes[ts_node]["region"]
        region_graph = self.graph["ts"].graph["region"]
        region_status = region_graph.nodes[region_name]["status"]

        # Reuse existing edges when the state has not changed.
        if (
            prod_node_data["marker"] == "visited"
            and region_status == "confirmed"
        ):
            for t_prod_node in self.successors(f_prod_node):
                yield (
                    t_prod_node,
                    self[f_prod_node][t_prod_node]["weight"],
                )
            return

        # Rebuild outgoing edges when the TS state has changed.
        self.remove_edges_from(list(self.out_edges(f_prod_node)))

        for t_ts_node, cost in self.graph["ts"].fly_successors(
            f_ts_node
        ):
            for t_buchi_node in self.graph["buchi"].successors(
                f_buchi_node
            ):
                t_prod_node = self.composition(
                    t_ts_node,
                    t_buchi_node,
                )

                label = self.graph["ts"].nodes[f_ts_node]["label"]

                truth, dist = check_label_for_buchi_edge(
                    self.graph["buchi"],
                    label,
                    f_buchi_node,
                    t_buchi_node,
                )

                total_weight = cost + self.graph["beta"] * dist

                if truth:
                    self.add_edge(
                        f_prod_node,
                        t_prod_node,
                        weight=total_weight,
                    )
                    yield t_prod_node, total_weight

        self.nodes[f_prod_node]["marker"] = "visited"

    # ------------------------------------
    # Get possible states from previous
    # possible set and a given TS state
    # ------------------------------------
    def get_possible_states(self, ts_node):
        new_reachable = set()
        # Go through each product state in possible states
        for f_s in self.possible_states:
            # Go through all connected states and if TS states match, add it to the list
            for t_s in self.successors(f_s):
                if t_s[0] == ts_node:
                    new_reachable.add(t_s)
        return new_reachable


class ProdAut_Run(object):
    # prefix, suffix in product run
    # prefix: init --> accept, suffix accept --> accept
    # line, loop in ts
    def __init__(self, product, prefix, precost, suffix, sufcost, totalcost):
        self.prefix = prefix
        self.precost = precost
        self.suffix = suffix
        self.sufcost = sufcost
        self.totalcost = totalcost
        self.prod_run_to_prod_edges()
        self.plan_output(product)

    def prod_run_to_prod_edges(self):
        """Convert product-state runs into reusable edge lists."""
        self.pre_prod_edges = list(
            zip(self.prefix, islice(self.prefix, 1, None))
        )

        if self.suffix:
            closed_suffix = self.suffix + [self.suffix[0]]
            self.suf_prod_edges = list(
                zip(
                    closed_suffix,
                    islice(closed_suffix, 1, None),
                )
            )
        else:
            self.suf_prod_edges = []

    def plan_output(self, product):

        # Collect the nodes of the TS associated with the prefix plan
        self.line = [product.nodes[node]['ts'] for node in self.prefix]
        # Collect the nodes of the TS associated with the suffix plan
        self.loop = [product.nodes[node]['ts'] for node in self.suffix]
        # Append start of loop to the end to create a 'loop'
        self.loop.append(self.loop[0])

        prefix_snapshot = tuple(self.line) if len(self.line) > 1 else ()
        suffix_snapshot = tuple(self.loop)

        # Collect prefix nodes in list of tuples e.g. [ (prefix_node_1,
        # prefix_node_2), (prefix_node_2, prefix_node_3), ..., (prefix_node_n-1,
        # prefix_node_n)]
        self.pre_ts_edges = zip(
            prefix_snapshot,
            islice(prefix_snapshot, 1, None),
        )
        # Collect suffix nodes in list of tuples (see pre_ts_edges)
        self.suf_ts_edges = zip(
            suffix_snapshot,
            islice(suffix_snapshot, 1, None),
        )

        # output plan --- for execution

        # Initialize prefix plan and cost
        self.pre_plan = list()
        # Initialize pre_plan cost
        self.pre_plan_cost = [0, ]

        ts_adjacency = None
        check_ts_adjacency = type(product.graph) is dict

        # Iterate over the nodes associated with the prefix (see pre_ts_edges)
        for ts_edge in self.pre_ts_edges:
            if check_ts_adjacency:
                ts = product.graph['ts']
                if type(ts) in (DiGraph, TSModel):
                    ts_adjacency = ts._adj
                check_ts_adjacency = False
            edge = (
                ts_adjacency[ts_edge[0]][ts_edge[1]]
                if ts_adjacency is not None
                else product.graph['ts'][ts_edge[0]][ts_edge[1]]
            )

            # Extract 'action' label between the two consecutive TS nodes of the
            # prefix plan and add it to the pre_plan
            self.pre_plan.append(edge['action'])

            # Add the 'weight' label between the two consectuve TS nodes as the cost
            # of the prefix plan
            self.pre_plan_cost.append(edge['weight'])  # action cost

        # Initialize suffix plan and cost
        self.suf_plan = list()
        self.suf_plan_cost = [0, ]

        # Iterate over the nodes associated with the suffix (see suf_ts_edges)
        for ts_edge in self.suf_ts_edges:
            if check_ts_adjacency:
                ts = product.graph['ts']
                if type(ts) in (DiGraph, TSModel):
                    ts_adjacency = ts._adj
                check_ts_adjacency = False
            edge = (
                ts_adjacency[ts_edge[0]][ts_edge[1]]
                if ts_adjacency is not None
                else product.graph['ts'][ts_edge[0]][ts_edge[1]]
            )

            # Extract 'action' label between the two consecutive TS nodes of the
            # suffix plan and add it to the suf_plan
            self.suf_plan.append(edge['action'])

            # Add 'weight' label between the consecutive TS nodes of the suffix plan to the cost
            self.suf_plan_cost.append(edge['weight'])  # action cost

        _LOGGER.info(
            "LTL Planner: Prefix plan: %s",
            self.pre_plan,
        )
        _LOGGER.info(
            "LTL Planner: Suffix plan: %s",
            self.suf_plan,
        )
