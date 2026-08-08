# Endpoints reference snapshot-local BuchiGraphNode IDs.
uint32 source_id
uint32 target_id

# Single Büchi edges use guard_formula. Safe Büchi edges use both
# hard_guard_formula and soft_guard_formula.
string guard_formula
string hard_guard_formula
string soft_guard_formula
