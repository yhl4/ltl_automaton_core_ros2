import os
from glob import glob

from setuptools import find_packages, setup


package_name = "ltl_automaton_execution"


setup(
    name=package_name,
    version="0.0.0",
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
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="yuhling",
    maintainer_email="1209634202@qq.com",
    description="Simulator-agnostic execution of retained LTL runs.",
    license="BSD-3-Clause",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            (
                "execution_node = "
                "ltl_automaton_execution.execution_node:main"
            ),
        ],
    },
)
