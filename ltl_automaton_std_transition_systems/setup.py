import os
from glob import glob

from setuptools import find_packages, setup


package_name = "ltl_automaton_std_transition_systems"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        ("share/" + package_name, ["package.xml", "README.md"]),
        (
            os.path.join("share", package_name, "launch"),
            glob("launch/*.launch.py"),
        ),
        (
            os.path.join("share", package_name, "config"),
            glob("config/*.yaml"),
        ),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="yuhling",
    maintainer_email="1209634202@qq.com",
    description=(
        "ROS 2 standard transition-system generators and state monitors."
    ),
    license="BSD-3-Clause",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            (
                "region_2d_pose_monitor = "
                "ltl_automaton_std_transition_systems."
                "region_2d_pose_monitor:main"
            ),
            (
                "region_6d_jointspace_monitor = "
                "ltl_automaton_std_transition_systems."
                "region_6d_jointspace_monitor:main"
            ),
            (
                "region_2d_pose_definition = "
                "ltl_automaton_std_transition_systems."
                "region_2d_pose_definition:main"
            ),
        ],
    },
)
