"""Isolate standard TS DDS tests from concurrently tested colcon packages."""

import os


# Set before collection so launched nodes inherit the same package domain.
os.environ["ROS_DOMAIN_ID"] = "218"
