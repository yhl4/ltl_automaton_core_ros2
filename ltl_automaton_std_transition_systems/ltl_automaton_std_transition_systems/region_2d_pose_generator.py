"""Generate grid-and-station transition systems for a planar pose."""

import math
from pathlib import Path

import yaml


def _action(region, position, quaternion):
    return {
        "type": "move",
        "weight": 10,
        "guard": "1",
        "attr": {
            "region": region,
            "pose": [position, quaternion],
        },
    }


def _station_intersects_square(station, center, side_length):
    """Return whether a station disk intersects an axis-aligned square."""
    half = side_length / 2.0
    dx = max(abs(station["origin"]["x"] - center[0]) - half, 0.0)
    dy = max(abs(station["origin"]["y"] - center[1]) - half, 0.0)
    margin = station["radius"] + station["dist_hysteresis"]
    return math.hypot(dx, dy) <= margin


def _connect(nodes, source, target):
    if target in nodes:
        nodes[source]["connected_to"][target] = "goto_" + target


def generate_regions_and_actions(definition):
    """Create a planner-compatible TS dictionary from a grid definition."""
    grid = definition["grid"]
    nodes = {}
    actions = {}

    for index, station in enumerate(definition.get("stations", [])):
        name = f"s{index}"
        yaw = station["origin"]["yaw"]
        quaternion = [0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)]
        nodes[name] = {
            "attr": {
                "type": "station",
                "pose": [
                    [station["origin"]["x"], station["origin"]["y"]],
                    [yaw],
                ],
                "radius": station["radius"],
                "angle_threshold": station["angle_threshold"],
                "dist_hysteresis": station["dist_hysteresis"],
                "angle_hysteresis": station["angle_hysteresis"],
            },
            "connected_to": {name: "goto_" + name},
        }
        actions["goto_" + name] = _action(
            name,
            [station["origin"]["x"], station["origin"]["y"], 0.0],
            quaternion,
        )

    cell_names = []
    centers = {}
    cell_index = 1
    for row in range(grid["number_of_cells_y"]):
        for column in range(grid["number_of_cells_x"]):
            name = f"r{cell_index}"
            x = grid["origin"]["x"] + (column + 0.5) * grid["cell_side_length"]
            y = grid["origin"]["y"] + (row + 0.5) * grid["cell_side_length"]
            nodes[name] = {
                "attr": {
                    "type": "square",
                    "pose": [[x, y], [0.0]],
                    "length": grid["cell_side_length"],
                    "hysteresis": grid["cell_hysteresis"],
                },
                "connected_to": {name: "goto_" + name},
            }
            actions["goto_" + name] = _action(
                name, [x, y, 0.0], [0.0, 0.0, 0.0, 1.0]
            )
            cell_names.append(name)
            centers[name] = (x, y)
            cell_index += 1

    width = grid["number_of_cells_x"]
    height = grid["number_of_cells_y"]
    for row in range(height):
        for column in range(width):
            name = cell_names[row * width + column]
            for next_row, next_column in (
                (row, column - 1),
                (row, column + 1),
                (row - 1, column),
                (row + 1, column),
            ):
                if 0 <= next_row < height and 0 <= next_column < width:
                    _connect(nodes, name, cell_names[next_row * width + next_column])

    for station_index, station in enumerate(definition.get("stations", [])):
        station_name = f"s{station_index}"
        for cell_name in cell_names:
            if _station_intersects_square(
                station, centers[cell_name], grid["cell_side_length"]
            ):
                _connect(nodes, station_name, cell_name)
                _connect(nodes, cell_name, station_name)

    initial_position = definition["initial_position"]
    initial = None
    for cell_name in cell_names:
        center = centers[cell_name]
        half = grid["cell_side_length"] / 2.0
        if (
            abs(initial_position[0] - center[0]) <= half
            and abs(initial_position[1] - center[1]) <= half
        ):
            initial = cell_name
            break
    if initial is None:
        raise ValueError("Initial position is outside the generated grid.")

    return {
        "state_dim": ["2d_pose_region"],
        "state_models": {
            "2d_pose_region": {
                "ts_type": "2d_pose_region",
                "initial": initial,
                "nodes": nodes,
            }
        },
        "actions": actions,
    }


def write_to_file(output_path, transition_system):
    """Write a generated transition system to an explicit output path."""
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(transition_system, stream, sort_keys=False)
    return path
