"""Pure serialization of internal transition-system state metadata."""


def flatten_state_dimension_names(raw_names) -> list[str]:
    """Flatten the TS state format retained by single or composed models."""
    dimension_names = []

    for name in raw_names:
        if isinstance(name, (list, tuple)):
            dimension_names.extend(str(item) for item in name)
        else:
            dimension_names.append(str(name))

    return dimension_names


def serialize_transition_state_values(state) -> list[str]:
    """Return one internal TS node as ordered string dimensions."""
    values = state if isinstance(state, tuple) else (state,)
    return [str(value) for value in values]
