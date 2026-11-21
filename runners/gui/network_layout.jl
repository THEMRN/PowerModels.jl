# Layout of a network for the GUI's Network page: a position for every bus of a case that has no
# coordinates, with the buses of a zone or an area kept together inside a circle of their own.
#
# The steps, in the order of calc_network_layout:
#   1. clusters: every group (zone or area) is split into its connected parts. A large part is a
#      cluster; a stray bus or a small pocket inside another group is laid out with the cluster it
#      is wired to, so one misplaced zone number does not pull the picture apart.
#   2. leaves: a bus with one line only (a generator behind its transformer, a load at the end of
#      a line) is set aside and drawn beside its bus at the end. Half the buses of a large case
#      are such leaves, and without them the rest has room.
#   3. first positions: stress majorization over the rest of the network, which puts two buses as
#      far apart as the path between them is long. It gives each cluster its shape and its side.
#   4. circles: one per cluster, with an area that follows its number of buses. They are arranged
#      by the same stress majorization on the clusters, from several starts, and the arrangement
#      with the fewest crossings of the lines between clusters is kept.
#   5. each cluster is moved into its circle, scaled to fit, and turned (or mirrored) so that its
#      lines to other clusters leave it on the side of those clusters.
#   6. spreading: buses of a cluster that are too close push each other apart and lines pull their
#      ends together, inside the circle, until the circle is filled evenly.
#   7. uncrossing: a bus whose lines cross others is moved to a place nearby where fewer cross.
#   8. the leaves go around their bus, into the widest free angle.
#
# The functions take plain arrays (buses are 1..bus_count) and nothing from PowerModels, and the
# result is the same every time for the same input. Lengths are in line lengths.

using LinearAlgebra

# ==================== Settings ====================
const LINE_LENGTH = 1.0             # ideal length of a line: the unit of the layout
const TRANSFORMER_LENGTH = 0.45     # ideal length of a transformer, so the buses of a substation stay together
const TIE_LENGTH = 2.5              # ideal length of a line between two clusters in the first positions, which keeps the clusters apart
const CLUSTER_SHARE = 0.25          # a part of a group is a cluster of its own from this share of the group's largest part
const BUS_AREA = 1.0                # area of a circle per bus that is not a leaf (line lengths²): sets how full a circle is
const LEAF_AREA = 0.3               # area of a circle per leaf
const LEAF_LENGTH = 0.5             # distance of a leaf from its bus
const LEAF_GAP = 0.3                # least distance between two leaves of a bus: more leaves stand farther out,
const LEAF_LENGTH_MOST = 1.2        # up to this distance from their bus
const LEAF_MARGIN = 0.15            # between a leaf and its cluster's circle, at least
const DISC_MARGIN = 0.7             # between the outermost bus of a cluster and its circle
const DISC_GAP = 0.9                # least distance between two circles
const PUSH_REACH = 1.25             # two buses without a line between them push each other when nearer than this
const LINE_PULL = 0.35              # pull of a line longer than its ideal length, as a share of the push of two buses equally too near
const TIE_PULL = 0.4                # pull of a line between two clusters on its ends, in line lengths per pass
const STRESS_SWEEPS = 300           # passes of the stress majorization over all buses
const SPREAD_SWEEPS = 400           # passes of the spreading
const SPREAD_STEP = 0.2             # largest move of a bus in the first spreading pass (line lengths); it shrinks to 0
const TURN_SWEEPS = 6               # passes that turn the clusters to face each other
const ARRANGEMENTS = 80             # arrangements of the circles that are tried; the best one is kept
const CROSSING_COST = 25.0          # cost of two bundles of lines between clusters crossing, in line lengths of such lines
const THROUGH_COST = 25.0           # cost of such a bundle passing through the middle of a third circle
const UNCROSS_SWEEPS = 10           # most passes that move single buses to uncross lines
const UNCROSS_STEPS = (0.4, 0.8, 1.4)   # distances (line lengths) of the places tried around a bus
const UNCROSS_DIRECTIONS = 8        # directions of the places tried around a bus
const BUS_GAP = 0.45                # least distance to the other buses of its cluster that a moved bus keeps
const SEPARATION_SWEEPS = 500       # most passes that move overlapping circles apart
const CIRCLE_STEPS = 400            # steps of the smallest-circle search


# ==================== Clusters ====================
"Neighbours of each bus: a vector of (other bus, edge index) per bus."
function find_neighbors(bus_count::Integer, edges)
    neighbors = [Tuple{Int,Int}[] for _ in 1:bus_count]
    for (index, (a, b)) in enumerate(edges)
        push!(neighbors[a], (b, index))
        push!(neighbors[b], (a, index))
    end
    return neighbors
end

"""
Connected parts of the groups, as vectors of buses: buses that reach each other through buses of
their own group only.
"""
function find_parts(neighbors, group_of_bus)
    bus_count = length(neighbors)
    seen = falses(bus_count)
    parts = Vector{Int}[]
    for start in 1:bus_count
        seen[start] && continue
        part = [start]
        seen[start] = true
        next = 1
        while next <= length(part)
            bus = part[next]
            next += 1
            for (other, _) in neighbors[bus]
                seen[other] && continue
                group_of_bus[other] == group_of_bus[bus] || continue
                seen[other] = true
                push!(part, other)
            end
        end
        push!(parts, part)
    end
    return parts
end

"""
Cluster of every bus, for the layout. A part of a group is a cluster when it has at least
CLUSTER_SHARE of the buses of the group's largest part. A smaller part (a stray) joins the
cluster most of its lines go to; a stray without a line to any cluster joins its own group's
largest cluster. Returns `cluster_of_bus` and `group_of_cluster`.
"""
function find_clusters(neighbors, group_of_bus)
    bus_count = length(neighbors)
    parts = find_parts(neighbors, group_of_bus)

    largest_part = Dict{Any,Int}()            # group => size of its largest part
    for part in parts
        group = group_of_bus[part[1]]
        largest_part[group] = max(get(largest_part, group, 0), length(part))
    end

    # the parts that are clusters, largest first so a group's first cluster is its largest
    cluster_of_bus = zeros(Int, bus_count)
    group_of_cluster = Any[]
    first_cluster = Dict{Any,Int}()           # group => its largest cluster
    for index in sortperm(parts, by=part -> (-length(part), part[1]))
        part = parts[index]
        group = group_of_bus[part[1]]
        length(part) >= CLUSTER_SHARE * largest_part[group] || continue
        push!(group_of_cluster, group)
        haskey(first_cluster, group) || (first_cluster[group] = length(group_of_cluster))
        cluster_of_bus[part] .= length(group_of_cluster)
    end

    # strays: each joins the cluster most of its lines go to; repeat for strays wired to strays only
    strays = [part for part in parts if cluster_of_bus[part[1]] == 0]
    while !isempty(strays)
        waiting = Vector{Int}[]
        joined = Tuple{Vector{Int},Int}[]
        for part in strays
            lines_to = Dict{Int,Int}()
            for bus in part, (other, _) in neighbors[bus]
                cluster = cluster_of_bus[other]
                cluster == 0 && continue
                lines_to[cluster] = get(lines_to, cluster, 0) + 1
            end
            if isempty(lines_to)
                push!(waiting, part)
            else
                most = maximum(values(lines_to))
                push!(joined, (part, minimum(cluster for (cluster, count) in lines_to if count == most)))
            end
        end
        for (part, cluster) in joined
            cluster_of_bus[part] .= cluster
        end
        if isempty(joined)                    # no line to any cluster: with their own group
            for part in waiting
                cluster_of_bus[part] .= first_cluster[group_of_bus[part[1]]]
            end
            break
        end
        strays = waiting
    end
    return cluster_of_bus, group_of_cluster
end


# ==================== Leaves ====================
"""
The bus each leaf hangs on (0 for a bus that is not a leaf). A leaf is a bus with one neighbour,
in its own cluster. Of two buses that have each other only, the first stays.
"""
function find_leaf_parents(neighbors, cluster_of_bus)
    bus_count = length(neighbors)
    parent_of_leaf = zeros(Int, bus_count)
    for bus in 1:bus_count
        length(neighbors[bus]) == 1 || continue
        parent = neighbors[bus][1][1]
        cluster_of_bus[parent] == cluster_of_bus[bus] || continue
        length(neighbors[parent]) == 1 && parent > bus && continue
        parent_of_leaf[bus] = parent
    end
    return parent_of_leaf
end

"""
Put the leaves around their bus, in place: into the widest angles left free by the bus's other
lines, evenly, LEAF_LENGTH away (farther when there are many, so that they keep LEAF_GAP), and
never nearer to their cluster's circle than LEAF_MARGIN.
"""
function place_leaves!(positions, neighbors, parent_of_leaf, cluster_of_bus, centers, radii)
    bus_count = length(neighbors)
    leaves_of = [Int[] for _ in 1:bus_count]
    for bus in 1:bus_count
        parent_of_leaf[bus] == 0 || push!(leaves_of[parent_of_leaf[bus]], bus)
    end
    for parent in 1:bus_count
        leaves = leaves_of[parent]
        isempty(leaves) && continue

        # angles of the bus's other lines, and the free angle after each of them (counter-clockwise)
        taken = Float64[]
        for (other, _) in neighbors[parent]
            parent_of_leaf[other] == parent && continue
            push!(taken, atan(positions[2, other] - positions[2, parent], positions[1, other] - positions[1, parent]))
        end
        sort!(taken)
        isempty(taken) && (taken = [-pi / 2])
        free = [index < length(taken) ? taken[index+1] - taken[index] : taken[1] + 2pi - taken[index] for index in eachindex(taken)]

        # each leaf goes into the free angle that leaves it most room
        leaves_in = zeros(Int, length(taken))
        for _ in leaves
            leaves_in[argmax([free[index] / (leaves_in[index] + 1) for index in eachindex(taken)])] += 1
        end
        next = 1
        for index in eachindex(taken)
            leaves_in[index] == 0 && continue
            step = free[index] / (leaves_in[index] + 1)
            distance = min(max(LEAF_LENGTH, LEAF_GAP / max(step, 1e-6)), LEAF_LENGTH_MOST)
            for place in 1:leaves_in[index]
                angle = taken[index] + place * step
                leaf = leaves[next]
                next += 1
                positions[1, leaf] = positions[1, parent] + distance * cos(angle)
                positions[2, leaf] = positions[2, parent] + distance * sin(angle)

                cluster = cluster_of_bus[leaf]                 # stay inside the circle
                room = radii[cluster] - LEAF_MARGIN
                dx = positions[1, leaf] - centers[1, cluster]
                dy = positions[2, leaf] - centers[2, cluster]
                from_center = sqrt(dx * dx + dy * dy)
                if from_center > room
                    positions[1, leaf] = centers[1, cluster] + dx * room / from_center
                    positions[2, leaf] = centers[2, cluster] + dy * room / from_center
                end
            end
        end
    end
    return positions
end


# ==================== Distances ====================
"Ideal length of each edge: TIE_LENGTH between two clusters, else TRANSFORMER_LENGTH or LINE_LENGTH."
function calc_edge_lengths(edges, is_transformer, cluster_of_bus)
    lengths = zeros(length(edges))
    for (index, (a, b)) in enumerate(edges)
        if cluster_of_bus[a] != cluster_of_bus[b]
            lengths[index] = TIE_LENGTH
        else
            lengths[index] = is_transformer[index] ? TRANSFORMER_LENGTH : LINE_LENGTH
        end
    end
    return lengths
end

"""
Shortest path length between every two buses, as a matrix. Buses with no path between them get
the longest path found plus two line lengths, which puts separate pieces side by side.
"""
function calc_distances(neighbors, lengths)
    bus_count = length(neighbors)
    distances = fill(Inf, bus_count, bus_count)
    queue = Int[]
    for source in 1:bus_count
        distance = view(distances, :, source)
        distance[source] = 0.0
        empty!(queue)
        push!(queue, source)
        next = 1
        while next <= length(queue)           # label correcting: a bus is queued again when a shorter path is found
            bus = queue[next]
            next += 1
            for (other, edge) in neighbors[bus]
                candidate = distance[bus] + lengths[edge]
                if candidate < distance[other] - 1e-12
                    distance[other] = candidate
                    push!(queue, other)
                end
            end
        end
    end
    longest = maximum(value for value in distances if isfinite(value))
    for index in eachindex(distances)
        isfinite(distances[index]) || (distances[index] = longest + 2 * LINE_LENGTH)
    end
    return distances
end


# ==================== First positions ====================
"""
Starting positions (2 x bus_count) from classical scaling: the two main directions of the
distance matrix. A tiny offset per bus keeps two buses from starting on the same point.
"""
function calc_start_positions(distances)
    bus_count = size(distances, 1)
    squared = distances .^ 2
    row_mean = sum(squared, dims=2) ./ bus_count
    centered = -0.5 .* (squared .- row_mean .- row_mean' .+ sum(squared) / bus_count^2)
    decomposition = eigen(Symmetric(centered))
    positions = zeros(2, bus_count)
    for axis in 1:2
        index = bus_count + 1 - axis                       # eigenvalues are sorted ascending
        index >= 1 || continue
        vector = decomposition.vectors[:, index]
        vector[argmax(abs.(vector))] < 0 && (vector = -vector)    # the sign is arbitrary: fix it
        positions[axis, :] = vector .* sqrt(max(decomposition.values[index], 0.0))
    end
    for bus in 1:bus_count
        positions[1, bus] += 1e-3 * cos(bus)
        positions[2, bus] += 1e-3 * sin(bus)
    end
    return positions
end

"""
Stress majorization, in place: each pass moves every bus to the place its distances to all the
others ask for, with the weight 1/distance² so that near buses count most.
"""
function improve_stress!(positions, distances; sweeps::Integer=STRESS_SWEEPS)
    bus_count = size(positions, 2)
    for _ in 1:sweeps
        for bus in 1:bus_count
            weight_sum = 0.0
            x_sum = 0.0
            y_sum = 0.0
            for other in 1:bus_count
                other == bus && continue
                distance = distances[other, bus]
                weight = 1.0 / (distance * distance)
                dx = positions[1, bus] - positions[1, other]
                dy = positions[2, bus] - positions[2, other]
                gap = max(sqrt(dx * dx + dy * dy), 1e-9)
                x_sum += weight * (positions[1, other] + distance * dx / gap)
                y_sum += weight * (positions[2, other] + distance * dy / gap)
                weight_sum += weight
            end
            weight_sum > 0 || continue
            positions[1, bus] = x_sum / weight_sum
            positions[2, bus] = y_sum / weight_sum
        end
    end
    return positions
end


# ==================== Circles ====================
"Centre (x, y) and radius of the smallest circle around the points (2 x n), to a small error."
function calc_enclosing_circle(points)
    count = size(points, 2)
    center = vec(sum(points, dims=2)) ./ count
    for step in 1:CIRCLE_STEPS                # move towards the farthest point, by less every step
        farthest = argmax([(points[1, i] - center[1])^2 + (points[2, i] - center[2])^2 for i in 1:count])
        center .+= (points[:, farthest] .- center) ./ (step + 1)
    end
    radius = sqrt(maximum((points[1, i] - center[1])^2 + (points[2, i] - center[2])^2 for i in 1:count))
    return center, radius
end

"""
Move the circles apart, in place, until every two are at least DISC_GAP from each other. Each of
two overlapping circles moves half of what is missing, along the line between their centres.
"""
function separate_circles!(centers, radii)
    count = length(radii)
    for _ in 1:SEPARATION_SWEEPS
        moved = false
        for a in 1:count, b in a+1:count
            dx = centers[1, b] - centers[1, a]
            dy = centers[2, b] - centers[2, a]
            gap = sqrt(dx * dx + dy * dy)
            missing = radii[a] + radii[b] + DISC_GAP - gap
            missing > 1e-6 || continue
            if gap < 1e-9                     # same centre: any direction, the same every time
                dx, dy, gap = cos(a + b), sin(a + b), 1.0
            end
            shift_x = 0.5 * missing * dx / gap
            shift_y = 0.5 * missing * dy / gap
            centers[1, a] -= shift_x
            centers[2, a] -= shift_y
            centers[1, b] += shift_x
            centers[2, b] += shift_y
            moved = true
        end
        moved || break
    end
    return centers
end

"Numbers in [0, 1) that look random and are the same in every run (a linear congruential generator)."
mutable struct Dice
    state::UInt64
end

function roll!(dice::Dice)
    dice.state = dice.state * 0x5851f42d4c957f2d + 0x14057b7ef767814f
    return (dice.state >> 11) / 2.0^53
end

"True when the segments a1-a2 and b1-b2 cross (points as (x, y))."
function is_crossing(a1, a2, b1, b2)
    side(p, q, r) = (q[1] - p[1]) * (r[2] - p[2]) - (q[2] - p[2]) * (r[1] - p[1])
    return side(a1, a2, b1) * side(a1, a2, b2) < 0 && side(b1, b2, a1) * side(b1, b2, a2) < 0
end

"Distance from the point p to the segment a-b."
function calc_segment_distance(p, a, b)
    dx, dy = b[1] - a[1], b[2] - a[2]
    along = ((p[1] - a[1]) * dx + (p[2] - a[2]) * dy) / max(dx * dx + dy * dy, 1e-12)
    along = clamp(along, 0.0, 1.0)
    return hypot(p[1] - (a[1] + along * dx), p[2] - (a[2] + along * dy))
end

"""
How untidy an arrangement of the circles is, in line lengths of lines between clusters. Each
bundle (the lines between two clusters, `line_counts` of them) costs its length between the two
circles, CROSSING_COST for every other bundle it crosses and up to THROUGH_COST for every third
circle it passes through.
"""
function calc_arrangement_cost(centers, radii, cluster_edges, line_counts)
    point(cluster) = (centers[1, cluster], centers[2, cluster])
    cost = 0.0
    for (index, (a, b)) in enumerate(cluster_edges)
        between = hypot(centers[1, a] - centers[1, b], centers[2, a] - centers[2, b]) - radii[a] - radii[b]
        cost += line_counts[index] * between
        for other in eachindex(radii)
            (other == a || other == b) && continue
            distance = calc_segment_distance(point(other), point(a), point(b))
            distance < radii[other] || continue
            cost += THROUGH_COST * line_counts[index] * (1 - distance / radii[other])
        end
        for later in index+1:length(cluster_edges)
            c, d = cluster_edges[later]
            (c == a || c == b || d == a || d == b) && continue
            is_crossing(point(a), point(b), point(c), point(d)) || continue
            cost += CROSSING_COST * line_counts[index] * line_counts[later]
        end
    end
    return cost
end

"""
Centres (2 x clusters) of circles with the given radii, arranged so that two clusters with lines
between them are neighbours and no two circles touch. Stress majorization on the clusters finds
an arrangement from a start; it is run from the clusters' first centres and from ARRANGEMENTS
other starts, and the arrangement that calc_arrangement_cost finds tidiest is kept.
"""
function calc_circle_centers(first_centers, radii, edges, cluster_of_bus)
    cluster_count = length(radii)
    cluster_count == 1 && return zeros(2, 1)

    # the clusters as a network: one edge per two clusters with lines between them, as long as their circles need
    lines_between = Dict{Tuple{Int,Int},Int}()
    for (a, b) in edges
        cluster_of_bus[a] == cluster_of_bus[b] && continue
        pair = minmax(cluster_of_bus[a], cluster_of_bus[b])
        lines_between[pair] = get(lines_between, pair, 0) + 1
    end
    cluster_edges = sort(collect(keys(lines_between)))
    line_counts = [lines_between[pair] for pair in cluster_edges]
    lengths = [radii[a] + radii[b] + DISC_GAP for (a, b) in cluster_edges]
    distances = calc_distances(find_neighbors(cluster_count, cluster_edges), lengths)

    # the first start: the first centres, brought to the size the circles need
    start = first_centers .- sum(first_centers, dims=2) ./ cluster_count
    wanted, found = 0.0, 0.0
    for a in 1:cluster_count, b in a+1:cluster_count
        wanted += distances[a, b]
        found += hypot(start[1, a] - start[1, b], start[2, a] - start[2, b])
    end
    found > 1e-9 && (start .*= wanted / found)

    best_centers, best_cost = start, Inf
    dice = Dice(cluster_count)
    spread = sum(radii)
    for attempt in 0:(cluster_count > 2 ? ARRANGEMENTS : 0)
        centers = attempt == 0 ? copy(start) : [spread * (roll!(dice) - 0.5) for _ in 1:2, _ in 1:cluster_count]
        improve_stress!(centers, distances)
        separate_circles!(centers, radii)
        cost = calc_arrangement_cost(centers, radii, cluster_edges, line_counts)
        if cost < best_cost - 1e-9
            best_centers, best_cost = centers, cost
        end
    end
    return best_centers
end

"""
The turn (2 x 2) and the middle that make the circles' picture widest left to right and centred
on (0, 0): new = turn * (old - middle). The direction is that of the largest spread of the
circles, each counted by its area.
"""
function calc_landscape_turn(centers, radii)
    weights = radii .^ 2
    middle = vec(sum(centers .* weights', dims=2)) ./ sum(weights)
    length(radii) == 1 && return [1.0 0.0; 0.0 1.0], middle
    centered = (centers .- middle) .* sqrt.(weights)'
    decomposition = eigen(Symmetric(centered * centered'))
    main = decomposition.vectors[:, 2]                      # direction of the largest spread
    main[argmax(abs.(main))] < 0 && (main = -main)
    return [main[1] main[2]; -main[2] main[1]], middle      # the rotation that puts `main` on the x axis
end


# ==================== Clusters into their circles ====================
"""
Move every cluster into its circle, in place: scaled about its own centre to fit the circle's
radius less DISC_MARGIN, and put on the circle's centre.
"""
function place_clusters!(positions, members, centers, radii)
    for cluster in eachindex(members)
        points = positions[:, members[cluster]]
        center, radius = calc_enclosing_circle(points)
        room = radii[cluster] - DISC_MARGIN
        scale = radius > 1e-9 ? room / radius : 1.0
        positions[:, members[cluster]] = (points .- center) .* scale .+ centers[:, cluster]
    end
    return positions
end

"""
Turn every cluster about its circle's centre, in place, so that its buses with lines to other
clusters are as near the other ends of those lines as a turn can bring them (the least sum of
their squared lengths). A cluster is mirrored first when that makes them shorter still, which
uncrosses lines that leave it side by side. Clusters are turned one after the other, in
TURN_SWEEPS passes, because each turn changes what the others should face.
"""
function turn_clusters!(positions, members, centers, edges, cluster_of_bus)
    ties = [Tuple{Int,Int}[] for _ in eachindex(members)]       # per cluster: (its bus, the other end)
    for (a, b) in edges
        cluster_of_bus[a] == cluster_of_bus[b] && continue
        push!(ties[cluster_of_bus[a]], (a, b))
        push!(ties[cluster_of_bus[b]], (b, a))
    end
    for _ in 1:TURN_SWEEPS, cluster in eachindex(members)
        isempty(ties[cluster]) && continue
        center_x, center_y = centers[1, cluster], centers[2, cluster]
        cross_sum, dot_sum = 0.0, 0.0                           # of each bus's place and its other end's, both from the centre
        mirrored_cross, mirrored_dot = 0.0, 0.0                 # the same with the cluster mirrored (y → -y)
        for (bus, other) in ties[cluster]
            ux, uy = positions[1, bus] - center_x, positions[2, bus] - center_y
            vx, vy = positions[1, other] - center_x, positions[2, other] - center_y
            cross_sum += ux * vy - uy * vx
            dot_sum += ux * vx + uy * vy
            mirrored_cross += ux * vy + uy * vx
            mirrored_dot += ux * vx - uy * vy
        end
        mirror = hypot(mirrored_cross, mirrored_dot) > hypot(cross_sum, dot_sum) + 1e-9
        angle = mirror ? atan(mirrored_cross, mirrored_dot) : atan(cross_sum, dot_sum)
        for bus in members[cluster]
            ux, uy = positions[1, bus] - center_x, positions[2, bus] - center_y
            mirror && (uy = -uy)
            positions[1, bus] = center_x + cos(angle) * ux - sin(angle) * uy
            positions[2, bus] = center_y + sin(angle) * ux + cos(angle) * uy
        end
    end
    return positions
end


# ==================== Spreading ====================
"""
Fill each circle evenly, in place. In every pass:
- two buses of a cluster without a line between them push each other apart when they are nearer
  than PUSH_REACH (more for buses with leaves: `room_of_bus` is the room each needs, 1 for a bus
  without leaves);
- a line pushes its ends apart when it is shorter than its ideal length and pulls them together,
  with LINE_PULL, when it is longer;
- a line to another cluster pulls its end towards the other end with the constant TIE_PULL.
A bus moves at most the pass's step, which shrinks to 0, and never leaves the circle's radius
less DISC_MARGIN.
"""
function spread_buses!(positions, members, centers, radii, edges, lengths, cluster_of_bus, room_of_bus)
    bus_count = size(positions, 2)
    moves = zeros(2, bus_count)
    joined = Set{Tuple{Int,Int}}(minmax(a, b) for (a, b) in edges)

    for sweep in 1:SPREAD_SWEEPS
        fill!(moves, 0.0)
        for cluster_members in members                      # pushes, between the buses of a cluster
            for i in eachindex(cluster_members), j in i+1:length(cluster_members)
                a, b = cluster_members[i], cluster_members[j]
                dx = positions[1, a] - positions[1, b]
                dy = positions[2, a] - positions[2, b]
                reach = PUSH_REACH * 0.5 * (room_of_bus[a] + room_of_bus[b])
                (abs(dx) < reach && abs(dy) < reach) || continue
                (a, b) in joined && continue
                gap = max(sqrt(dx * dx + dy * dy), 1e-6)
                gap < reach || continue
                push = (reach - gap) / gap
                moves[1, a] += push * dx
                moves[2, a] += push * dy
                moves[1, b] -= push * dx
                moves[2, b] -= push * dy
            end
        end
        for (index, (a, b)) in enumerate(edges)             # the lines: a spring within a cluster, a pull between two
            dx = positions[1, a] - positions[1, b]
            dy = positions[2, a] - positions[2, b]
            gap = max(sqrt(dx * dx + dy * dy), 1e-6)
            if cluster_of_bus[a] != cluster_of_bus[b]
                pull = TIE_PULL / gap
            elseif gap > lengths[index]
                pull = LINE_PULL * (gap - lengths[index]) / gap
            else
                pull = -(lengths[index] - gap) / gap
            end
            moves[1, a] -= pull * dx
            moves[2, a] -= pull * dy
            moves[1, b] += pull * dx
            moves[2, b] += pull * dy
        end

        step = SPREAD_STEP * (1 - (sweep - 1) / SPREAD_SWEEPS)
        for cluster in eachindex(members), bus in members[cluster]
            length_of_move = sqrt(moves[1, bus]^2 + moves[2, bus]^2)
            length_of_move > 1e-12 || continue
            limited = min(length_of_move, step) / length_of_move
            positions[1, bus] += limited * moves[1, bus]
            positions[2, bus] += limited * moves[2, bus]

            room = radii[cluster] - DISC_MARGIN              # stay inside the circle
            dx = positions[1, bus] - centers[1, cluster]
            dy = positions[2, bus] - centers[2, cluster]
            from_center = sqrt(dx * dx + dy * dy)
            if from_center > room
                positions[1, bus] = centers[1, cluster] + dx * room / from_center
                positions[2, bus] = centers[2, cluster] + dy * room / from_center
            end
        end
    end
    return positions
end


# ==================== Uncrossing ====================
"Number of lines that the lines of `bus` would cross with the bus at (x, y)."
function count_crossings(bus::Integer, x::Real, y::Real, positions, neighbors, edges)
    count = 0
    for (other, _) in neighbors[bus]
        other_end = (positions[1, other], positions[2, other])
        for (a, b) in edges
            (a == bus || b == bus || a == other || b == other) && continue
            is_crossing((x, y), other_end, (positions[1, a], positions[2, a]), (positions[1, b], positions[2, b])) && (count += 1)
        end
    end
    return count
end

"""
Move single buses to uncross lines, in place. A bus whose lines cross others is tried at the
middle of its neighbours and at places around itself (UNCROSS_STEPS away, in UNCROSS_DIRECTIONS
directions). It moves to the place where the fewest lines cross, when those are fewer than now,
the place is inside its circle and no other bus of its cluster is nearer than BUS_GAP. Every
move takes crossings away, so the passes end, at the latest after UNCROSS_SWEEPS.
"""
function reduce_crossings!(positions, members, centers, radii, edges, cluster_of_bus)
    neighbors = find_neighbors(size(positions, 2), edges)
    for _ in 1:UNCROSS_SWEEPS
        moved = false
        for cluster in eachindex(members), bus in members[cluster]
            isempty(neighbors[bus]) && continue
            fewest = count_crossings(bus, positions[1, bus], positions[2, bus], positions, neighbors, edges)
            fewest == 0 && continue

            # the places to try: the middle of the neighbours, then around the bus
            places = Tuple{Float64,Float64}[]
            middle_x = sum(positions[1, other] for (other, _) in neighbors[bus]) / length(neighbors[bus])
            middle_y = sum(positions[2, other] for (other, _) in neighbors[bus]) / length(neighbors[bus])
            push!(places, (middle_x, middle_y))
            push!(places, (0.5 * (middle_x + positions[1, bus]), 0.5 * (middle_y + positions[2, bus])))
            for step in UNCROSS_STEPS, direction in 1:UNCROSS_DIRECTIONS
                angle = 2pi * direction / UNCROSS_DIRECTIONS
                push!(places, (positions[1, bus] + step * cos(angle), positions[2, bus] + step * sin(angle)))
            end

            best = nothing
            room = radii[cluster] - DISC_MARGIN
            for (x, y) in places
                hypot(x - centers[1, cluster], y - centers[2, cluster]) <= room || continue
                any(other != bus && hypot(x - positions[1, other], y - positions[2, other]) < BUS_GAP for other in members[cluster]) && continue
                crossings = count_crossings(bus, x, y, positions, neighbors, edges)
                if crossings < fewest
                    best, fewest = (x, y), crossings
                end
            end
            best === nothing && continue
            positions[1, bus], positions[2, bus] = best
            moved = true
        end
        moved || break
    end
    return positions
end


# ==================== The layout ====================
"""
Positions of the buses 1..bus_count of a network, and the circle of each cluster.

- `edges`: one (bus, bus) per connected pair of buses, and `is_transformer` for each of them;
- `group_of_bus`: the zone or area of each bus (any values; all the same for no groups).

Returns `x` and `y` (line lengths, centred on 0, widest left to right), `cluster_of_bus`, and
`clusters`: for each one its `group`, its `buses`, and the `x`, `y` and `radius` of its circle.
A cluster's buses are those laid out in its circle, strays of other groups among them.
"""
function calc_network_layout(bus_count::Integer, edges, is_transformer, group_of_bus)
    neighbors = find_neighbors(bus_count, edges)
    cluster_of_bus, group_of_cluster = find_clusters(neighbors, group_of_bus)
    cluster_count = length(group_of_cluster)
    members = [findall(==(cluster), cluster_of_bus) for cluster in 1:cluster_count]

    # the leaves are set aside; `inner` are the buses laid out by the steps that follow
    parent_of_leaf = find_leaf_parents(neighbors, cluster_of_bus)
    inner = findall(==(0), parent_of_leaf)
    inner_index = zeros(Int, bus_count)
    inner_index[inner] = 1:length(inner)
    leaf_count = zeros(Int, bus_count)
    for bus in 1:bus_count
        parent_of_leaf[bus] == 0 || (leaf_count[parent_of_leaf[bus]] += 1)
    end
    inner_edges = Tuple{Int,Int}[]
    inner_transformer = Bool[]
    for (index, (a, b)) in enumerate(edges)
        (parent_of_leaf[a] == 0 && parent_of_leaf[b] == 0) || continue
        push!(inner_edges, (inner_index[a], inner_index[b]))
        push!(inner_transformer, is_transformer[index])
    end
    inner_cluster = cluster_of_bus[inner]
    inner_members = [findall(==(cluster), inner_cluster) for cluster in 1:cluster_count]
    area_of_inner = [BUS_AREA + LEAF_AREA * leaf_count[bus] for bus in inner]

    # first positions of these buses at once: the clusters come apart through the long lines between them
    inner_neighbors = find_neighbors(length(inner), inner_edges)
    lengths = calc_edge_lengths(inner_edges, inner_transformer, inner_cluster)
    positions = zeros(2, length(inner))
    if length(inner) > 1
        distances = calc_distances(inner_neighbors, lengths)
        positions = calc_start_positions(distances)
        improve_stress!(positions, distances)
    end

    # the circles: an area that follows the number of buses, arranged as the clusters are in the first positions
    radii = [sqrt(sum(area_of_inner[inner_members[cluster]]) / pi) + DISC_MARGIN for cluster in 1:cluster_count]
    first_centers = zeros(2, cluster_count)
    for cluster in 1:cluster_count
        first_centers[:, cluster] = sum(positions[:, inner_members[cluster]], dims=2) ./ length(inner_members[cluster])
    end
    centers = calc_circle_centers(first_centers, radii, inner_edges, inner_cluster)

    # every cluster into its circle and turned, spread until the circle is filled evenly, then lines uncrossed
    place_clusters!(positions, inner_members, centers, radii)
    turn_clusters!(positions, inner_members, centers, inner_edges, inner_cluster)
    spread_buses!(positions, inner_members, centers, radii, inner_edges, lengths, inner_cluster, sqrt.(area_of_inner ./ BUS_AREA))
    reduce_crossings!(positions, inner_members, centers, radii, inner_edges, inner_cluster)

    # all buses again, the leaves around their bus
    all_positions = zeros(2, bus_count)
    all_positions[:, inner] = positions
    place_leaves!(all_positions, neighbors, parent_of_leaf, cluster_of_bus, centers, radii)

    # widest left to right, centred
    turn, middle = calc_landscape_turn(centers, radii)
    all_positions = turn * (all_positions .- middle)
    centers = turn * (centers .- middle)

    clusters = [
        (group=group_of_cluster[cluster], buses=members[cluster], x=centers[1, cluster], y=centers[2, cluster], radius=radii[cluster])
        for cluster in 1:cluster_count
    ]
    return (x=all_positions[1, :], y=all_positions[2, :], cluster_of_bus=cluster_of_bus, clusters=clusters)
end
