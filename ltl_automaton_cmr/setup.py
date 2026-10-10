from glob import glob

from setuptools import find_packages, setup


package_name = "ltl_automaton_cmr"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "tests"]),
    package_data={package_name: ["assets/*.json"]},
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml", "LICENSE", "README.md", "provenance.json"]),
        ("share/" + package_name + "/config", glob("config/*.json") + glob("config/*.yaml")),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/docs", glob("docs/*.md")),
    ],
    install_requires=["setuptools"],
    python_requires=">=3.10",
    zip_safe=True,
    maintainer="yuhling",
    maintainer_email="1209634202@qq.com",
    description="Independent certified CMR engine and ROS 2 execution adapter.",
    license="MIT",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "cmr_plan = ltl_automaton_cmr.cli:main",
            "cmr_node = ltl_automaton_cmr.ros_node:main",
        ],
    },
)
