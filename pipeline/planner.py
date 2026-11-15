"""Slope-aware route planner (A* on a raster grid). Pure numpy, no GDAL needed, so it is easy to test."""
import heapq
import math

import numpy as np

SQRT2 = math.sqrt(2)
NEIGHBOURS = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1),
              (-1, -1, SQRT2), (-1, 1, SQRT2), (1, -1, SQRT2), (1, 1, SQRT2)]


def cost_grid(slope_deg, max_slope=15.0, blocked=None, slope_weight=4.0):
    """Cost per cell: 1 on flat ground, rising with slope; inf where impassable.
    Suited astronauts are slow and unstable on slopes, so cost grows with the square of the slope."""
    s = np.nan_to_num(slope_deg.astype("float64"), nan=90.0)
    cost = 1.0 + slope_weight * (s / max_slope) ** 2
    cost[s > max_slope] = np.inf
    if blocked is not None:
        cost[blocked.astype(bool)] = np.inf
    return cost


def astar(cost, start, goal):
    """Least-cost 8-connected path from start (row, col) to goal. Returns list of (row, col)."""
    rows, cols = cost.shape
    if not np.isfinite(cost[start]) or not np.isfinite(cost[goal]):
        raise ValueError(f"start {start} or goal {goal} is on impassable ground; move the waypoint")
    gscore = np.full(cost.shape, np.inf)
    gscore[start] = 0.0
    came = {}
    hmin = float(np.min(cost[np.isfinite(cost)]))
    h = lambda r, c: hmin * math.hypot(r - goal[0], c - goal[1])
    open_ = [(h(*start), 0.0, start)]
    while open_:
        _, g, cur = heapq.heappop(open_)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        if g > gscore[cur]:
            continue
        r, c = cur
        for dr, dc, step in NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                cc = cost[nr, nc]
                if not np.isfinite(cc):
                    continue
                ng = g + step * (cost[r, c] + cc) / 2
                if ng < gscore[nr, nc]:
                    gscore[nr, nc] = ng
                    came[(nr, nc)] = cur
                    heapq.heappush(open_, (ng + h(nr, nc), ng, (nr, nc)))
    raise ValueError(f"no safe path from {start} to {goal}; raise max_slope or move waypoints")


def plan_through(cost, waypoints_rc):
    """Chain A* through all waypoints in order."""
    full = []
    for a, b in zip(waypoints_rc, waypoints_rc[1:]):
        seg = astar(cost, a, b)
        full.extend(seg if not full else seg[1:])
    return full
