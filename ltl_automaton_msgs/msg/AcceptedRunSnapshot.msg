# Product-state sequences reference snapshot-local ProductGraphNode IDs.
uint32[] prefix_product_node_ids

# The final suffix node connects back to the first through a Product edge.
# The first suffix node is not repeated at the end of this sequence.
uint32[] suffix_product_node_ids

# Costs are retained directly by the active ProdAut_Run.
float64 prefix_cost
float64 suffix_cost
float64 total_cost
