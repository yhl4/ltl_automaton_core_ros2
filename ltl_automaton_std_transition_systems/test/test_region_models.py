import math
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


def _two_cell_definition(initial_position, hysteresis=0.0):
    """Create the two-cell fixture used for exact grid-boundary checks."""
    return {
        "grid": {
            "origin": {"x": 0.0, "y": 0.0},
            "cell_side_length": 1.0,
            "cell_hysteresis": hysteresis,
            "number_of_cells_x": 2,
            "number_of_cells_y": 1,
        },
        "stations": [],
        "initial_position": list(initial_position),
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
    "initial_position",
    [(1.0, 0.5), (0.0, 0.5), (0.5, 0.0), (0.0, 0.0)],
)
def test_generator_rejects_exact_grid_boundaries(initial_position):
    """Reject initial points excluded by strict monitor square membership."""
    with pytest.raises(ValueError, match="outside"):
        generate_regions_and_actions(_two_cell_definition(initial_position))


@pytest.mark.parametrize(
    "initial_position, expected",
    [
        ((math.nextafter(1.0, 0.0), 0.5), "r1"),
        ((math.nextafter(1.0, 2.0), 0.5), "r2"),
    ],
)
def test_generator_and_fresh_monitor_agree_just_inside_cells(
    initial_position, expected
):
    """Keep generator and fresh monitor classification aligned near a boundary."""
    transition_system = generate_regions_and_actions(
        _two_cell_definition(initial_position)
    )
    assert transition_system["state_models"]["2d_pose_region"]["initial"] == expected
    model = Region2DPoseModel(
        transition_system["state_models"]["2d_pose_region"]
    )
    assert model.update(_pose(*initial_position)) == expected


def test_positive_hysteresis_keeps_shared_boundary_in_current_cell():
    """Preserve existing hysteresis behavior after entering the first cell."""
    definition = _two_cell_definition((0.5, 0.5), hysteresis=0.05)
    transition_system = generate_regions_and_actions(definition)
    assert transition_system["state_models"]["2d_pose_region"]["initial"] == "r1"
    model = Region2DPoseModel(
        transition_system["state_models"]["2d_pose_region"]
    )
    assert model.update(_pose(0.5, 0.5)) == "r1"
    assert model.update(_pose(1.0, 0.5)) == "r1"


@pytest.mark.parametrize("side", [0.0, -1.0])
def test_generator_rejects_degenerate_grid_cells(side):
    definition = _definition()
    definition["grid"]["cell_side_length"] = side
    definition["initial_position"] = [0.0, 0.0]

    with pytest.raises(ValueError, match="side length must be positive"):
        generate_regions_and_actions(definition)


@pytest.mark.parametrize(
    "field, value",
    [
        ("cell_side_length", float("nan")),
        ("cell_hysteresis", float("inf")),
        ("station_x", float("nan")),
        ("station_yaw", float("inf")),
        ("station_radius", float("inf")),
        ("initial_x", float("nan")),
    ],
)
def test_generator_rejects_nonfinite_geometry(field, value):
    definition = _definition()
    if field.startswith("cell_"):
        definition["grid"][field] = value
    elif field == "initial_x":
        definition["initial_position"][0] = value
    elif field == "station_radius":
        definition["stations"][0]["radius"] = value
    else:
        key = "x" if field == "station_x" else "yaw"
        definition["stations"][0]["origin"][key] = value

    with pytest.raises(ValueError, match="geometry must be finite"):
        generate_regions_and_actions(definition)


def test_generator_rejects_nonfinite_derived_cell_center():
    definition = _definition()
    definition["grid"]["cell_side_length"] = 1e308
    definition["grid"]["origin"]["x"] = 1e308

    with pytest.raises(ValueError, match="cell centers must be finite"):
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


@pytest.mark.parametrize("invalid", ["x_nan", "y_inf", "quaternion_nan", "zero_quaternion"])
def test_2d_model_rejects_invalid_pose_without_changing_region(invalid):
    transition_system = generate_regions_and_actions(_definition())
    model = Region2DPoseModel(transition_system["state_models"]["2d_pose_region"])
    assert model.update(_pose(0.2, 0.2)) == "r1"
    model.station_access_request = "s0"
    pose = _pose(0.5, 0.5)
    if invalid == "x_nan":
        pose.position.x = float("nan")
    elif invalid == "y_inf":
        pose.position.y = float("inf")
    elif invalid == "quaternion_nan":
        pose.orientation.z = float("nan")
    else:
        pose.orientation.w = 0.0

    with pytest.raises(ValueError):
        model.update(pose)
    with pytest.raises(ValueError):
        model.closest_region(pose)
    assert model.state == "r1"
    assert model.update(_pose(1.5, 0.5)) == "r2"


@pytest.mark.parametrize("invalid", [10**400, -(10**400)], ids=["positive", "negative"])
def test_2d_model_normalizes_python_pose_overflow_and_preserves_state(invalid):
    """Keep the finite-value diagnostic for oversized Python pose components."""
    transition_system = generate_regions_and_actions(_definition())
    model = Region2DPoseModel(transition_system["state_models"]["2d_pose_region"])
    assert model.update(_pose(0.2, 0.2)) == "r1"
    model.station_access_request = "s0"
    for component, name in (("position", "x"), ("orientation", "w")):
        pose = _pose(0.5, 0.5)
        setattr(getattr(pose, component), name, invalid)
        before_position = dict(vars(pose.position))
        before_orientation = dict(vars(pose.orientation))
        for validate in (model.update, model.closest_region):
            with pytest.raises(ValueError) as caught:
                validate(pose)
            assert str(caught.value) == "Pose position and orientation must be finite numbers."
            assert isinstance(caught.value.__cause__, OverflowError)
            assert vars(pose.position) == before_position
            assert vars(pose.orientation) == before_orientation
            assert model.state == "r1"
            assert model.station_access_request == "s0"
    valid = _pose(1.5, 0.5)
    valid.position.z = invalid  # The planar model continues to ignore the z coordinate.
    assert model.update(valid) == "r2"


def _joint_model(radius=1.0):
    return Region6DJointspaceModel({
        "nodes": {
            "a": {
                "attr": {"position": [0.0] * 6, "radius": radius},
                "connected_to": {"a": "stay"},
            },
        },
    })


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_6d_model_rejects_nonfinite_joint_feedback(invalid):
    model = _joint_model()
    assert model.update([0.0] * 6) == ("a", True)
    position = [0.0] * 5 + [invalid]

    with pytest.raises(ValueError, match="finite"):
        model.update(position)
    with pytest.raises(ValueError, match="finite"):
        model.is_in_region(position, "a")
    assert model.state == "a"
    assert model.update([0.0] * 6) == ("a", True)


def test_6d_model_ignores_extra_joints_and_keeps_strict_radius():
    model = _joint_model()
    assert model.update([0.0] * 6 + [float("nan")]) == ("a", True)
    assert model.is_in_region([0.5] + [0.0] * 5, "a")
    assert not model.is_in_region([1.0] + [0.0] * 5, "a")


@pytest.mark.parametrize("invalid", [10**400, -(10**400)], ids=["positive", "negative"])
def test_6d_model_normalizes_python_coordinate_overflow_and_preserves_state(invalid):
    """Classify float conversion overflow without changing the last valid region."""
    model = _joint_model()
    assert model.update([0.0] * 6) == ("a", True)
    for index in (0, 5):
        position = [0.0] * 6
        position[index] = invalid
        before = list(position)
        for validate in (model.update, lambda values: model.is_in_region(values, "a")):
            with pytest.raises(ValueError) as caught:
                validate(position)
            assert str(caught.value) == "JointState positions must be finite numbers."
            assert isinstance(caught.value.__cause__, OverflowError)
            assert position == before
            assert model.state == "a"
    assert model.update([0.0] * 6 + [invalid]) == ("a", True)
    assert model.update([0.5] + [0.0] * 5) == ("a", True)


def test_6d_model_distance_does_not_overflow_for_finite_positions():
    model = _joint_model(radius=1e201)
    # sqrt(6) * 1e200 is less than 1e201; squaring 1e200 overflows a float.
    assert model.update([1e200] * 6) == ("a", True)
