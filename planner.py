"""Deterministic, capacity-constrained allocation for synthetic food-rescue plans."""

import csv
import heapq
import io
import math
import re
from collections import Counter
from dataclasses import dataclass

CATEGORIES = ("produce", "bakery", "chilled")
VERSION = "1.0"
MAX_LOCATIONS = 20


class ValidationError(ValueError):
    pass


def _fields(value, required, path):
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must be an object.")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required)
    if missing:
        raise ValidationError(f"{path}: missing {', '.join(sorted(missing))}.")
    if extra:
        raise ValidationError(f"{path}: unknown fields {', '.join(sorted(extra))}.")


def _number(value, low, high, path, integer=False):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValidationError(f"{path} must be a finite number.")
    if integer and type(value) is not int:
        raise ValidationError(f"{path} must be a whole number.")
    if not low <= value <= high:
        raise ValidationError(f"{path} must be between {low} and {high}.")


def _text(value, path, identifier=False):
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValidationError(f"{path} must be non-empty text of at most 80 characters.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValidationError(f"{path} must not contain control characters.")
    if identifier and not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value):
        raise ValidationError(f"{path} must use 1-40 letters, digits, underscores or hyphens.")


def validate(scenario):
    _fields(scenario, (
        "name", "start_minute", "speed_kph", "handling_minutes", "max_leg_km",
        "vehicle_capacity", "donors", "hubs",
    ), "scenario")
    _text(scenario["name"], "name")
    _number(scenario["start_minute"], 0, 1439, "start_minute", True)
    _number(scenario["speed_kph"], 1, 100, "speed_kph")
    _number(scenario["handling_minutes"], 0, 120, "handling_minutes", True)
    _number(scenario["max_leg_km"], 0.1, 30, "max_leg_km")
    _number(scenario["vehicle_capacity"], 1, 1000, "vehicle_capacity", True)
    ids = set()
    for kind in ("donors", "hubs"):
        if not isinstance(scenario[kind], list) or len(scenario[kind]) > MAX_LOCATIONS:
            raise ValidationError(f"{kind} must be a list of at most {MAX_LOCATIONS} locations.")
        for index, item in enumerate(scenario[kind]):
            path = f"{kind}[{index}]"
            common = ("id", "name", "x_km", "y_km")
            specific = (
                ("quantity", "category", "ready_minute", "expires_minute")
                if kind == "donors" else
                ("demand", "capacity", "accepts", "cold_storage", "open_minute", "close_minute")
            )
            _fields(item, common + specific, path)
            _text(item["id"], f"{path}.id", True)
            _text(item["name"], f"{path}.name")
            if item["id"] in ids:
                raise ValidationError(f"{path}.id must be unique across all locations.")
            ids.add(item["id"])
            for axis in ("x_km", "y_km"):
                _number(item[axis], 0, 20, f"{path}.{axis}")
            if kind == "donors":
                _number(item["quantity"], 0, 10000, f"{path}.quantity", True)
                if item["category"] not in CATEGORIES:
                    raise ValidationError(f"{path}.category must be produce, bakery or chilled.")
                start, end = "ready_minute", "expires_minute"
            else:
                for key in ("demand", "capacity"):
                    _number(item[key], 0, 10000, f"{path}.{key}", True)
                accepts = item["accepts"]
                if (not isinstance(accepts, list) or not 1 <= len(accepts) <= 3
                        or any(type(value) is not str or value not in CATEGORIES for value in accepts)
                        or len(set(accepts)) != len(accepts)):
                    raise ValidationError(f"{path}.accepts must contain unique food categories.")
                if type(item["cold_storage"]) is not bool:
                    raise ValidationError(f"{path}.cold_storage must be true or false.")
                start, end = "open_minute", "close_minute"
            for key in (start, end):
                _number(item[key], 0, 1439, f"{path}.{key}", True)
            if item[end] < item[start]:
                raise ValidationError(f"{path}.{end} must not precede {start}; use same-day windows.")
    return scenario


def eligibility(scenario, donor, hub):
    distance = math.hypot(donor["x_km"] - hub["x_km"], donor["y_km"] - hub["y_km"])
    travel = math.ceil(distance / scenario["speed_kph"] * 60)
    duration = travel + scenario["handling_minutes"]
    departure = max(scenario["start_minute"], donor["ready_minute"], hub["open_minute"] - duration)
    arrival = departure + duration
    reasons = []
    if donor["category"] not in hub["accepts"]:
        reasons.append("category")
    if donor["category"] == "chilled" and not hub["cold_storage"]:
        reasons.append("cold_storage")
    if distance > scenario["max_leg_km"]:
        reasons.append("distance")
    if arrival > donor["expires_minute"]:
        reasons.append("expiry")
    if arrival > hub["close_minute"]:
        reasons.append("closed")
    if not hub["capacity"] or not hub["demand"]:
        reasons.append("no_capacity")
    return {
        "donor_id": donor["id"], "hub_id": hub["id"],
        "eligible": not reasons, "reasons": reasons,
        "distance_km": round(distance, 6), "cost_meters": round(distance * 1000),
        "depart_minute": departure, "arrive_minute": arrival,
    }


@dataclass
class Edge:
    target: int
    reverse: int
    capacity: int
    cost: int


def _optimal_allocations(donors, hubs, pairs):
    """Successive shortest paths: maximum flow, then minimum serving-meter cost."""
    source, sink = len(donors) + len(hubs), len(donors) + len(hubs) + 1
    graph = [[] for _ in range(sink + 1)]

    def add_edge(start, end, capacity, cost):
        edge = Edge(end, len(graph[end]), capacity, cost)
        graph[start].append(edge)
        graph[end].append(Edge(start, len(graph[start]) - 1, 0, -cost))
        return edge

    for index, donor in enumerate(donors):
        add_edge(source, index, donor["quantity"], 0)
    for index, hub in enumerate(hubs):
        add_edge(len(donors) + index, sink, min(hub["demand"], hub["capacity"]), 0)
    donor_indexes = {donor["id"]: index for index, donor in enumerate(donors)}
    hub_indexes = {hub["id"]: len(donors) + index for index, hub in enumerate(hubs)}
    tracked = []
    for pair in pairs:
        if pair["eligible"]:
            capacity = donors[donor_indexes[pair["donor_id"]]]["quantity"]
            edge = add_edge(donor_indexes[pair["donor_id"]], hub_indexes[pair["hub_id"]],
                            capacity, pair["cost_meters"])
            tracked.append((pair, edge, capacity))
    potentials = [0] * len(graph)
    while True:
        distances = [math.inf] * len(graph)
        previous = [None] * len(graph)
        distances[source] = 0
        queue = [(0, source)]
        while queue:
            distance, node = heapq.heappop(queue)
            if distance != distances[node]:
                continue
            for index, edge in enumerate(graph[node]):
                if edge.capacity <= 0:
                    continue
                candidate = distance + edge.cost + potentials[node] - potentials[edge.target]
                if candidate < distances[edge.target]:
                    distances[edge.target] = candidate
                    previous[edge.target] = (node, index)
                    heapq.heappush(queue, (candidate, edge.target))
        if previous[sink] is None:
            break
        for node, distance in enumerate(distances):
            if distance != math.inf:
                potentials[node] += distance
        amount, node = math.inf, sink
        while node != source:
            parent, index = previous[node]
            amount = min(amount, graph[parent][index].capacity)
            node = parent
        node = sink
        while node != source:
            parent, index = previous[node]
            edge = graph[parent][index]
            edge.capacity -= amount
            graph[node][edge.reverse].capacity += amount
            node = parent
    return [(pair, initial - edge.capacity) for pair, edge, initial in tracked
            if initial > edge.capacity]


def _greedy_allocations(donors, hubs, pairs):
    remaining = {hub["id"]: min(hub["demand"], hub["capacity"]) for hub in hubs}
    allocations = []
    for donor in sorted(donors, key=lambda item: (item["expires_minute"], item["id"])):
        supply = donor["quantity"]
        eligible = [pair for pair in pairs if pair["donor_id"] == donor["id"] and pair["eligible"]]
        for pair in sorted(eligible, key=lambda item: (item["cost_meters"], item["hub_id"])):
            amount = min(supply, remaining[pair["hub_id"]])
            if amount:
                allocations.append((pair, amount))
                remaining[pair["hub_id"]] -= amount
                supply -= amount
    return allocations


REASONS = {
    "category": "Food category not accepted",
    "cold_storage": "Chilled food needs cold storage",
    "distance": "Beyond the maximum direct-leg distance",
    "expiry": "Earliest delivery is after the batch expiry",
    "closed": "Earliest delivery is after hub closing",
    "no_capacity": "Hub has no demand or receiving capacity",
}


def plan(scenario):
    validate(scenario)
    donors = sorted(scenario["donors"], key=lambda item: item["id"])
    hubs = sorted(scenario["hubs"], key=lambda item: item["id"])
    pairs = [eligibility(scenario, donor, hub) for donor in donors for hub in hubs]
    optimized = _optimal_allocations(donors, hubs, pairs)
    greedy = _greedy_allocations(donors, hubs, pairs)
    available = sum(donor["quantity"] for donor in donors)
    demand = sum(hub["demand"] for hub in hubs)
    capacity = scenario["vehicle_capacity"]

    def summarize(allocations):
        allocated = sum(amount for _, amount in allocations)
        return {
            "available": available, "demand": demand, "allocated": allocated,
            "coverage_pct": round(100 * allocated / demand, 1) if demand else 0,
            "unassigned": available - allocated, "unmet": demand - allocated,
            "serving_km": round(sum(pair["cost_meters"] * amount for pair, amount in allocations) / 1000, 3),
            "trips": sum(math.ceil(amount / capacity) for _, amount in allocations),
            "trip_km": round(sum(pair["distance_km"] * math.ceil(amount / capacity)
                                 for pair, amount in allocations), 2),
        }

    transfers = []
    allocated_donors, allocated_hubs = Counter(), Counter()
    for pair, amount in optimized:
        transfers.append({
            "donor_id": pair["donor_id"], "hub_id": pair["hub_id"],
            "quantity": amount, "distance_km": round(pair["distance_km"], 2),
            "depart_minute": pair["depart_minute"], "arrive_minute": pair["arrive_minute"],
            "trips": math.ceil(amount / capacity),
        })
        allocated_donors[pair["donor_id"]] += amount
        allocated_hubs[pair["hub_id"]] += amount
    donor_details = []
    for donor in donors:
        donor_pairs = [pair for pair in pairs if pair["donor_id"] == donor["id"]]
        blocked = Counter(reason for pair in donor_pairs for reason in pair["reasons"])
        remaining = donor["quantity"] - allocated_donors[donor["id"]]
        if not remaining:
            explanation = "All available servings are assigned."
        elif not hubs:
            explanation = "No receiving hubs in this scenario."
        elif not any(pair["eligible"] for pair in donor_pairs):
            explanation = "No eligible receiving hub. Review the constraints below."
        else:
            explanation = "Eligible receiving capacity is used by this or other batches in the maximum-coverage plan."
        donor_details.append({
            "id": donor["id"], "allocated": allocated_donors[donor["id"]], "remaining": remaining,
            "explanation": explanation,
            "constraints": [{"code": code, "hubs": count, "text": REASONS[code]}
                            for code, count in sorted(blocked.items())],
        })
    hub_details = []
    for hub in hubs:
        received = allocated_hubs[hub["id"]]
        unmet = hub["demand"] - received
        if not unmet:
            explanation = "Demand is fully covered."
        elif received == hub["capacity"]:
            explanation = "Receiving capacity is the bottleneck; demand is higher than capacity."
        elif not any(pair["eligible"] and next(d["quantity"] for d in donors if d["id"] == pair["donor_id"])
                     for pair in pairs if pair["hub_id"] == hub["id"]):
            explanation = "No eligible batch with available supply."
        else:
            explanation = "Compatible supply is exhausted across the network; coverage is not an equity guarantee."
        hub_details.append({
            "id": hub["id"], "received": received, "unmet": unmet, "explanation": explanation,
            "coverage_pct": round(100 * received / hub["demand"], 1) if hub["demand"] else 0,
        })
    summary, baseline = summarize(optimized), summarize(greedy)
    return {
        "version": VERSION, "summary": summary, "baseline": baseline,
        "improvement": summary["allocated"] - baseline["allocated"],
        "transfers": transfers, "donors": donor_details, "hubs": hub_details,
        "pairs": pairs, "reason_labels": REASONS,
    }


def csv_export(scenario, result):
    def safe(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("donor", "hub", "category", "servings", "direct_km", "depart", "arrive", "parallel_loads"))
    donors = {item["id"]: item for item in scenario["donors"]}
    hubs = {item["id"]: item for item in scenario["hubs"]}
    for transfer in result["transfers"]:
        donor = donors[transfer["donor_id"]]
        times = [f"{transfer[key] // 60:02}:{transfer[key] % 60:02}" for key in ("depart_minute", "arrive_minute")]
        writer.writerow((
            safe(donor["name"]), safe(hubs[transfer["hub_id"]]["name"]), donor["category"],
            transfer["quantity"], transfer["distance_km"], *times, transfer["trips"],
        ))
    return output.getvalue()
