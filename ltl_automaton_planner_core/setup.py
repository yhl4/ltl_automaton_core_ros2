from setuptools import find_packages, setup

package_name = 'ltl_automaton_planner_core'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test', 'test.*']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        (
            'share/' + package_name,
            ['package.xml'],
        ),
    ],
    install_requires=[
        'setuptools',
    ],
    zip_safe=True,
    maintainer='yuhling',
    maintainer_email='1209634202@qq.com',
    description=(
        'ROS-independent planning core for the LTL automaton planner.'
    ),
    license='MIT',
    python_requires='>=3.10',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [],
    },
)
