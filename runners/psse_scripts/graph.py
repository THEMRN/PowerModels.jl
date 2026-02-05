import networkx as nx

g = {
    3011: [3001],
    101: [151],
    204: [201, 205],
    3003: [3001, 3005],
    154: [153, 203, 205, 3008],
    3005: [3003, 3004, 3006, 3007, 3008],
    211: [201],
    203: [154, 202, 205],
    206: [205],
    3004: [152, 3002, 3005],
    3006: [153, 3005],
    205: [154, 203, 204, 206],
    201: [151, 202, 204, 211],
    3008: [154, 3005, 3007, 3018],
    151: [101, 102, 152, 201],
    3001: [3002, 3003, 3011],
    152: [151, 153, 202, 3004],
    3018: [3008],
    202: [152, 201, 203],
    3002: [3001, 3004],
    102: [151],
    3007: [3005, 3008],
    153: [152, 154, 3006],
}


def all_v1_v2_min_cuts(G, V1, V2):
    """
    Returns all distinct minimal cuts that separate any node in V1 from any node in V2.
    G: undirected NetworkX graph (weighted or unweighted)
    V1, V2: disjoint lists or sets of nodes
    capacity: edge attribute name for weight/capacity
    """
    # Step 1: build Gomory–Hu tree (use unit capacities if capacity is None)
    nx.set_edge_attributes(G, 1, "capacity")
    T = nx.gomory_hu_tree(G)

    cuts = []
    seen_partitions = set()

    # Step 2: loop over all pairs (v1, v2)
    for s in V1:
        for t in V2:
            # Get the minimum cut value using unit capacities if capacity is None
            cut_value, partition = nx.minimum_cut(G, s, t)

            reachable, non_reachable = partition

            # Normalize partition as frozenset of reachable nodes
            key = frozenset(reachable)
            if key not in seen_partitions:
                seen_partitions.add(key)

                # Extract edges crossing the cut
                cut_edges = [(u, v) for u in reachable for v in G[u] if v in non_reachable]

                cuts.append(
                    {
                        "s": s,
                        "t": t,
                        "cut_value": cut_value,
                        "cut_edges": cut_edges,
                        "side1": set(reachable),
                        "side2": set(non_reachable),
                    }
                )

    return cuts


g = nx.from_dict_of_lists(g)
v1 = {3001, 3003, 3011, 3005}
V2 = set(g.nodes) - v1

cuts = all_v1_v2_min_cuts(g, v1, V2)
print(f"nodes in graph: {len(g.nodes)}")
print(f"edges in graph: {len(g.edges)}")
print(f"number of cuts found: {len(cuts)}")
for cut in cuts:
    print("----------------------")
    print("Cut between", cut["s"], "and", cut["t"])
    print("Cut value:", cut["cut_value"])
    print("Cut edges:", cut["cut_edges"])
    print("len side1:", len(cut["side1"]), "side2:", len(cut["side2"]))
    print("side1:", cut["side1"])
    print("side2:", cut["side2"])
