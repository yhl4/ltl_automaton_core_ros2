# Opaque, non-empty identity of the PlannerNode lifetime that owns this
# observation.
string planner_instance_id

# Active accepted planning generation within this planner instance.
uint64 planning_generation

# Snapshot-local Product node IDs representing the complete 0/1/N
# currently possible Product-state set.
uint32[] possible_product_node_ids

# Whether a planner-selected next action is currently available.
bool has_next_action

# Planner-selected next action for this same formal observation.
# Meaningful only when has_next_action is true.
string next_action
