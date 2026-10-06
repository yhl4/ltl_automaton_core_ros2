"""Load and convert transition-system YAML data."""

from math import isfinite
from numbers import Real

import yaml
from networkx import DiGraph

from ..boolean_formulas.parser import parse as parse_guard


def import_ts_from_file(transition_system_textfile):
    """Load a transition-system dictionary from YAML text or a stream."""
    try:
        transition_system = yaml.safe_load(transition_system_textfile)
    except yaml.YAMLError as error:
        raise ValueError(
            "Cannot load transition system from YAML."
        ) from error

    if not isinstance(transition_system, dict):
        raise ValueError(
            "Transition-system YAML must contain a mapping."
        )

    return transition_system


def state_models_from_ts(ts_dict, initial_states_dict=None):
    """Convert a transition-system dictionary into directed state models."""
    dimensions = ts_dict["state_dim"]
    if (
        not isinstance(dimensions, list) or not dimensions
        or any(not isinstance(name, str) or not name for name in dimensions)
        or len(set(dimensions)) != len(dimensions)
    ):
        raise ValueError("state_dim must be a nonempty list of unique strings.")

    models = ts_dict["state_models"]
    actions = ts_dict["actions"]
    if not isinstance(models, dict) or not isinstance(actions, dict):
        raise ValueError("state_models and actions must be mappings.")
    validated_actions = set()

    if initial_states_dict is not None:
        if set(initial_states_dict) != set(dimensions):
            raise ValueError(
                "Initial states do not match the transition-system dimensions."
            )

    state_models = []

    for model_dim in dimensions:
        state_model_dict = models[model_dim]
        nodes = state_model_dict["nodes"]
        if (
            not isinstance(nodes, dict) or not nodes
            or any(not isinstance(node, str) or not node for node in nodes)
        ):
            raise ValueError(f"Nodes in {model_dim!r} must be nonempty named states.")

        state_model = DiGraph(
            initial=set(),
            ts_state_format=[str(model_dim)],
        )

        for node in nodes:
            state_model.add_node(
                (node,),
                label={str(node)},
            )

        if initial_states_dict is None:
            initial_state = state_model_dict["initial"]
        else:
            initial_state = initial_states_dict[model_dim]

        if initial_state not in nodes:
            raise ValueError(
                f"Initial state {initial_state!r} is not defined "
                f"for transition-system dimension {model_dim!r}."
            )

        state_model.graph["initial"] = {
            (initial_state,),
        }

        for node, node_data in nodes.items():
            connections = node_data["connected_to"]
            if not isinstance(connections, dict):
                raise ValueError(f"connected_to for {node!r} must be a mapping.")
            for connected_node, action in connections.items():
                if connected_node not in nodes:
                    raise ValueError(f"Undefined transition target {connected_node!r}.")
                if not isinstance(action, str) or not action or action not in actions:
                    raise ValueError(f"Undefined transition action {action!r}.")
                action_data = actions[action]
                if action not in validated_actions:
                    weight = action_data["weight"]
                    if (
                        isinstance(weight, bool) or not isinstance(weight, Real)
                        or not isfinite(weight) or weight < 0
                    ):
                        raise ValueError(
                            f"Action {action!r} weight must be finite and nonnegative."
                        )
                    parse_guard(action_data["guard"])
                    validated_actions.add(action)

                state_model.add_edge(
                    (node,),
                    (connected_node,),
                    action=action,
                    guard=action_data["guard"],
                    weight=action_data["weight"],
                )

        state_models.append(state_model)

    return state_models
