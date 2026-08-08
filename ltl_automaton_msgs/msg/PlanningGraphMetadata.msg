# Identify one successfully committed active planning snapshot.
uint64 planning_generation
string active_ts_sha256

# Explain which formal task produced the active Büchi automaton.
string hard_task
string soft_task
string buchi_type

# Describe the full graph sizes, including when payload is unavailable.
uint32 buchi_node_count
uint32 buchi_edge_count
uint32 product_node_count
uint32 product_edge_count

# Snapshot availability is independent from planning success. When unavailable,
# graph arrays are empty and unavailable_reason explains why; no old graph may
# be returned for this generation.
bool available
string unavailable_reason
