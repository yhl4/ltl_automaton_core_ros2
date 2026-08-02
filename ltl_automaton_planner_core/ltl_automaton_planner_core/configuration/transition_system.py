"""Load and convert transition-system YAML data."""

import yaml
from networkx import DiGraph


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

    if initial_states_dict is not None:
        if set(initial_states_dict) != set(dimensions):
            raise ValueError(
                "Initial states do not match the transition-system dimensions."
            )

    state_models = []

    for model_dim in dimensions:
        state_model_dict = ts_dict["state_models"][model_dim]

        state_model = DiGraph(
            initial=set(),
            ts_state_format=[str(model_dim)],
        )

        for node in state_model_dict["nodes"]:
            state_model.add_node(
                (node,),
                label={str(node)},
            )

        if initial_states_dict is None:
            initial_state = state_model_dict["initial"]
        else:
            initial_state = initial_states_dict[model_dim]

        state_model.graph["initial"] = {
            (initial_state,),
        }

        for node, node_data in state_model_dict["nodes"].items():
            for connected_node, action in node_data["connected_to"].items():
                action_data = ts_dict["actions"][action]

                state_model.add_edge(
                    (node,),
                    (connected_node,),
                    action=action,
                    guard=action_data["guard"],
                    weight=action_data["weight"],
                )

        state_models.append(state_model)

    return state_models
