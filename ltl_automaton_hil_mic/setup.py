import os
from glob import glob

from setuptools import find_packages, setup


package_name = "ltl_automaton_hil_mic"


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
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="yuhling",
    maintainer_email="1209634202@qq.com",
    description="ROS 2 human-in-the-loop mixed-initiative controllers.",
    license="BSD-3-Clause",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            (
                "bool_cmd_hil_mic = "
                "ltl_automaton_hil_mic.bool_cmd_mixer:main"
            ),
            (
                "vel_cmd_hil_mic = "
                "ltl_automaton_hil_mic.vel_cmd_mixer:main"
            ),
        ],
    },
)
