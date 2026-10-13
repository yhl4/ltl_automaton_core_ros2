import hashlib, json, sys
import rclpy
from ltl_automaton_planner_core.ltl_tools import discrete_plan
print(json.dumps({'python':sys.executable,'rclpy':rclpy.__file__,'discrete_plan':discrete_plan.__file__,'discrete_plan_sha256':hashlib.sha256(open(discrete_plan.__file__,'rb').read()).hexdigest()},sort_keys=True))
