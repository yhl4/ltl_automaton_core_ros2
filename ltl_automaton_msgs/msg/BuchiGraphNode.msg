# Snapshot-local identifier. It is stable only within one retained generation.
uint32 id
string display_label
bool initial
bool accepting

# A single hard/soft Büchi node uses state and level -1.
# A safe Büchi node uses hard_state, soft_state, and its actual level.
int32 LEVEL_NOT_APPLICABLE=-1
string state
string hard_state
string soft_state
int32 acceptance_level
