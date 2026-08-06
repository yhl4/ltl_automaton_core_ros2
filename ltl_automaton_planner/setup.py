import os
from glob import glob

from setuptools import find_packages, setup


package_name = "ltl_automaton_planner"


setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        (
            "share/" + package_name,
            ["package.xml"],
        ),
        (
            os.path.join(
                "share",
                package_name,
                "launch",
            ),
            glob("launch/*.launch.py"),
        ),
        (
            os.path.join(
                "share",
                package_name,
                "config",
            ),
            glob("config/*.yaml"),
        ),
        (
            os.path.join(
                "share",
                package_name,
                "docs",
            ),
            glob("docs/*.md"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="yuhling",
    maintainer_email="1209634202@qq.com",
    description="ROS2 wrapper node for the LTL planner core.",
    license="BSD-3-Clause",
    extras_require={
        "test": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            (
                "planner_node = "
                "ltl_automaton_planner.planner_node:main"
            ),
            (
                "kth_demo_driver = "
                "ltl_automaton_planner.kth_demo_driver:main"
            ),
        ],
    },
)
