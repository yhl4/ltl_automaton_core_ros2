# Product-state sequences reference snapshot-local ProductGraphNode IDs.
uint32[] prefix_product_node_ids

# The final suffix node connects back to the first through a Product edge.
# Every entry is a real node occurrence; repeated nodes retain their order.
# A closing marker is not appended: the final-to-first edge is implicit.
# A final revisit to the first node therefore requires a real self-loop.
uint32[] suffix_product_node_ids

# Costs are retained directly by the active ProdAut_Run.
float64 prefix_cost
float64 suffix_cost
float64 total_cost
