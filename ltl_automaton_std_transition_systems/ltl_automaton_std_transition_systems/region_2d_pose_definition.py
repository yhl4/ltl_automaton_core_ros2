"""Interactive command for defining a planar-region transition system."""

import argparse

from .region_2d_pose_generator import generate_regions_and_actions, write_to_file


def _numbers(prompt, count, cast=float):
    while True:
        try:
            values = [cast(value.strip()) for value in input(prompt).split(",")]
            if len(values) == count:
                return values
        except ValueError:
            pass
        print(f"Please enter exactly {count} comma-separated values.")


def collect_definition():
    """Collect the legacy grid and station inputs from the terminal."""
    origin_x, origin_y = _numbers("Grid origin x,y: ", 2)
    side, hysteresis = _numbers("Cell side length,hysteresis: ", 2)
    cells_x, cells_y = _numbers("Number of cells x,y: ", 2, int)
    stations = []
    print("Stations: x,y,yaw,radius,angle threshold,distance hysteresis,angle hysteresis")
    while True:
        line = input("Station (or 'end'): ").strip()
        if line == "end":
            break
        try:
            values = [float(value.strip()) for value in line.split(",")]
        except ValueError:
            values = []
        if len(values) != 7:
            print("Please enter seven comma-separated values.")
            continue
        stations.append(
            {
                "origin": {"x": values[0], "y": values[1], "yaw": values[2]},
                "radius": values[3],
                "angle_threshold": values[4],
                "dist_hysteresis": values[5],
                "angle_hysteresis": values[6],
            }
        )
    initial_position = _numbers("Initial position x,y: ", 2)
    return {
        "grid": {
            "origin": {"x": origin_x, "y": origin_y},
            "cell_side_length": side,
            "cell_hysteresis": hysteresis,
            "number_of_cells_x": cells_x,
            "number_of_cells_y": cells_y,
        },
        "stations": stations,
        "initial_position": initial_position,
    }


def main():
    """Run the interactive TS definition utility."""
    parser = argparse.ArgumentParser()
    parser.add_argument("output", help="Output YAML path")
    args = parser.parse_args()
    path = write_to_file(
        args.output,
        generate_regions_and_actions(collect_definition()),
    )
    print(f"Transition system written to {path}")
