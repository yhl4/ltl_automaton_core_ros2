# Opaque, non-empty identity of the PlannerNode lifetime that owns this
# observation.
string planner_instance_id

# Active accepted planning generation within this planner instance.
uint64 planning_generation

# Planner-owned command-cursor step within this accepted generation.
# Starts at zero on commit, advances on accepted expected TS feedback, and
# remains unchanged on republication. It is not backend completion evidence.
uint64 execution_step_seq

# Snapshot-local Product node IDs representing the complete 0/1/N
# currently possible Product-state set.
uint32[] possible_product_node_ids

# Whether a planner-selected next action is currently available.
bool has_next_action

# Planner-selected next action for this same formal observation.
# Meaningful only when has_next_action is true.
string next_action
