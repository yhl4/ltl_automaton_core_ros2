from types import SimpleNamespace

from geometry_msgs.msg import (
    Pose,
    PoseStamped,
    PoseWithCovariance,
    PoseWithCovarianceStamped,
)
import pytest

from ltl_automaton_planner_core.configuration.transition_system import (
    state_models_from_ts,
)
from ltl_automaton_std_transition_systems.region_2d_pose_generator import (
    generate_regions_and_actions,
)
from ltl_automaton_std_transition_systems.region_2d_pose_monitor import (
    Region2DPoseModel,
    _pose_from_message,
)
from ltl_automaton_std_transition_systems.region_6d_jointspace_monitor import (
    Region6DJointspaceModel,
)


def _pose(x, y, yaw=0.0):
    return SimpleNamespace(
        position=SimpleNamespace(x=x, y=y),
        orientation=SimpleNamespace(
            x=0.0,
            y=0.0,
            z=__import__("math").sin(yaw / 2.0),
            w=__import__("math").cos(yaw / 2.0),
        ),
    )


def _definition():
    return {
        "grid": {
            "origin": {"x": 0.0, "y": 0.0},
            "cell_side_length": 1.0,
            "cell_hysteresis": 0.05,
            "number_of_cells_x": 2,
            "number_of_cells_y": 1,
        },
        "stations": [
            {
                "origin": {"x": 0.5, "y": 0.5, "yaw": 0.0},
                "radius": 0.1,
                "angle_threshold": 0.2,
                "dist_hysteresis": 0.05,
                "angle_hysteresis": 0.1,
            }
        ],
        "initial_position": [0.2, 0.2],
    }


def test_generated_ts_is_accepted_by_planner_core():
    transition_system = generate_regions_and_actions(_definition())

    assert transition_system["state_models"]["2d_pose_region"]["initial"] == "r1"
    assert all(
        action["guard"] == "1"
        for action in transition_system["actions"].values()
    )
    state_models = state_models_from_ts(transition_system)
    assert state_models[0].graph["initial"] == {("r1",)}


def test_generator_rejects_initial_position_outside_grid():
    definition = _definition()
    definition["initial_position"] = [4.0, 4.0]

    with pytest.raises(ValueError, match="outside"):
        generate_regions_and_actions(definition)


@pytest.mark.parametrize(
    "message, expected",
    [
        (Pose(), lambda message: message),
        (PoseStamped(), lambda message: message.pose),
        (PoseWithCovariance(), lambda message: message.pose),
        (PoseWithCovarianceStamped(), lambda message: message.pose.pose),
    ],
)
def test_supported_pose_messages_are_normalized(message, expected):
    assert _pose_from_message(message) is expected(message)


def test_2d_model_tracks_cells_station_request_and_closest_region():
    transition_system = generate_regions_and_actions(_definition())
    model = Region2DPoseModel(
        transition_system["state_models"]["2d_pose_region"]
    )

    assert model.update(_pose(0.5, 0.5)) == "r1"
    closest, distance = model.closest_region(_pose(0.5, 0.5))
    assert closest == "s0"
    assert distance == pytest.approx(-0.1)

    model.station_access_request = "s0"
    assert model.update(_pose(0.5, 0.5)) == "s0"
    model.station_access_request = ""
    assert model.update(_pose(0.5, 0.5)) == "r1"
    assert model.update(_pose(1.5, 0.5)) == "r2"


def test_6d_model_reports_connected_and_unconnected_transitions():
    model = Region6DJointspaceModel(
        {
            "nodes": {
                "a": {
                    "attr": {"position": [0.0] * 6, "radius": 0.2},
                    "connected_to": {"a": "stay", "b": "move"},
                },
                "b": {
                    "attr": {"position": [1.0] * 6, "radius": 0.2},
                    "connected_to": {"a": "move", "b": "stay"},
                },
                "c": {
                    "attr": {"position": [2.0] * 6, "radius": 0.2},
                    "connected_to": {"c": "stay"},
                },
            }
        }
    )

    assert model.update([0.0] * 6) == ("a", True)
    assert model.update([1.0] * 6) == ("b", True)
    assert model.update([2.0] * 6) == ("c", False)
    with pytest.raises(ValueError, match="six"):
        model.update([0.0] * 5)
