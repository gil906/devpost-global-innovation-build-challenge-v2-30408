import copy
import csv
import io
import itertools
import json
import random
import unittest
from pathlib import Path

from planner import ValidationError, csv_export, eligibility, plan, validate

ROOT = Path(__file__).resolve().parents[1]


def demo():
    return json.loads((ROOT / "data/demo.json").read_text())


def tiny():
    scenario = demo()
    scenario["donors"] = [{
        "id": "d", "name": "Batch", "x_km": 0, "y_km": 0, "quantity": 10,
        "category": "produce", "ready_minute": 600, "expires_minute": 720,
    }]
    scenario["hubs"] = [{
        "id": "h", "name": "Hub", "x_km": 3, "y_km": 4, "demand": 10, "capacity": 10,
        "accepts": ["produce"], "cold_storage": False, "open_minute": 600, "close_minute": 720,
    }]
    return scenario


class PlannerTests(unittest.TestCase):
    def test_demo_beats_greedy_by_exactly_sixty(self):
        result = plan(demo())
        self.assertEqual(result["summary"], {
            "available": 270, "demand": 230, "allocated": 230, "coverage_pct": 100.0,
            "unassigned": 40, "unmet": 0, "serving_km": 684.0, "trips": 10, "trip_km": 28.3,
        })
        self.assertEqual(result["baseline"]["allocated"], 170)
        self.assertEqual(result["improvement"], 60)
        bakery = next(item for item in result["transfers"] if item["donor_id"] == "bakery")
        self.assertEqual(bakery["hub_id"], "breakfast")
        self.assertEqual(bakery["arrive_minute"], 627)

    def test_deterministic_without_mutation_or_input_order_dependence(self):
        scenario = demo()
        original = copy.deepcopy(scenario)
        expected = plan(scenario)
        self.assertEqual(scenario, original)
        self.assertEqual(plan(scenario), expected)
        scenario["donors"].reverse()
        scenario["hubs"].reverse()
        self.assertEqual(plan(scenario), expected)

    def test_exact_time_and_distance_boundaries(self):
        scenario = tiny()
        scenario.update(speed_kph=60, handling_minutes=0, max_leg_km=5)
        donor, hub = scenario["donors"][0], scenario["hubs"][0]
        donor["expires_minute"] = hub["close_minute"] = 605
        self.assertEqual(plan(scenario)["summary"]["allocated"], 10)
        scenario["max_leg_km"] = 4.999
        self.assertIn("distance", eligibility(scenario, donor, hub)["reasons"])
        scenario["max_leg_km"] = 5
        donor["expires_minute"] = 604
        self.assertIn("expiry", eligibility(scenario, donor, hub)["reasons"])
        self.assertEqual(plan(scenario)["summary"]["allocated"], 0)

    def test_waits_for_hub_opening_and_rounds_travel_up(self):
        scenario = tiny()
        scenario["speed_kph"] = 19
        scenario["hubs"][0]["open_minute"] = 700
        pair = eligibility(scenario, scenario["donors"][0], scenario["hubs"][0])
        self.assertEqual(pair["arrive_minute"], 700)
        self.assertEqual(pair["depart_minute"], 674)
        self.assertTrue(pair["eligible"])
        scenario["donors"][0]["expires_minute"] = 699
        self.assertEqual(plan(scenario)["summary"]["allocated"], 0)

    def test_start_after_hub_closing_and_ready_time(self):
        scenario = tiny()
        scenario["start_minute"] = 715
        self.assertIn("closed", plan(scenario)["pairs"][0]["reasons"])
        scenario["start_minute"] = 600
        scenario["donors"][0]["ready_minute"] = 710
        self.assertIn("closed", plan(scenario)["pairs"][0]["reasons"])

    def test_chilled_needs_acceptance_and_cold_storage(self):
        scenario = tiny()
        scenario["donors"][0]["category"] = "chilled"
        pair = plan(scenario)["pairs"][0]
        self.assertEqual(pair["reasons"], ["category", "cold_storage"])
        scenario["hubs"][0]["accepts"] = ["chilled"]
        self.assertEqual(plan(scenario)["summary"]["allocated"], 0)
        scenario["hubs"][0]["cold_storage"] = True
        self.assertEqual(plan(scenario)["summary"]["allocated"], 10)

    def test_hub_capacity_and_vehicle_loads(self):
        scenario = tiny()
        scenario["hubs"][0]["capacity"] = 7
        scenario["vehicle_capacity"] = 3
        result = plan(scenario)
        self.assertEqual(result["summary"]["allocated"], 7)
        self.assertEqual(result["summary"]["trips"], 3)
        self.assertEqual(result["summary"]["trip_km"], 15)
        self.assertEqual(result["hubs"][0]["unmet"], 3)
        self.assertIn("capacity is the bottleneck", result["hubs"][0]["explanation"])
        scenario["hubs"][0]["capacity"] = 0
        self.assertEqual(plan(scenario)["summary"]["allocated"], 0)

    def test_empty_and_zero_scenarios(self):
        for key in ("donors", "hubs"):
            scenario = tiny()
            scenario[key] = []
            self.assertEqual(plan(scenario)["summary"]["allocated"], 0)
        scenario = tiny()
        scenario["hubs"][0]["demand"] = 0
        result = plan(scenario)
        self.assertEqual(result["summary"]["coverage_pct"], 0)
        self.assertEqual(result["summary"]["allocated"], 0)
        scenario["hubs"] = []
        scenario["donors"] = []
        self.assertEqual(plan(scenario)["transfers"], [])

    def test_distance_sensitivity_and_unassigned_explanations(self):
        scenario = demo()
        scenario["max_leg_km"] = 2
        result = plan(scenario)
        self.assertLess(result["summary"]["allocated"], 230)
        deli = next(item for item in result["donors"] if item["id"] == "deli")
        self.assertEqual(deli["remaining"], 20)
        self.assertIn("No eligible", deli["explanation"])
        self.assertTrue(any(item["code"] == "distance" for item in deli["constraints"]))

    def test_csv_has_exact_rows_and_neutralizes_formulas(self):
        scenario = tiny()
        scenario["donors"][0]["name"] = '  =HYPERLINK("https://example.invalid")'
        scenario["hubs"][0]["name"] = "@SUM(1,2)"
        output = csv_export(scenario, plan(scenario))
        rows = list(csv.reader(io.StringIO(output)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 8)
        self.assertTrue(rows[1][0].startswith("'"))
        self.assertTrue(rows[1][1].startswith("'"))
        self.assertEqual(rows[1][3], "10")
        scenario["donors"][0]["quantity"] = 0
        self.assertEqual(len(list(csv.reader(io.StringIO(csv_export(scenario, plan(scenario)))))), 1)

    def test_strict_validation_rejects_bad_inputs(self):
        mutations = [
            lambda s: s.update(extra="instructions"),
            lambda s: s.update(name=""),
            lambda s: s.update(start_minute=True),
            lambda s: s.update(speed_kph=float("nan")),
            lambda s: s.update(speed_kph=float("inf")),
            lambda s: s.update(speed_kph=10 ** 400),
            lambda s: s.update(donors={}),
            lambda s: s.update(donors=s["donors"] * 21),
            lambda s: s["donors"][0].update(quantity=1.5),
            lambda s: s["donors"][0].update(name="bad\nname"),
            lambda s: s["donors"][0].update(name="x" * 81),
            lambda s: s["donors"][0].update(id="../path"),
            lambda s: s["donors"][0].update(x_km=-1),
            lambda s: s["donors"][0].update(category="unknown"),
            lambda s: s["donors"][0].update(expires_minute=599),
            lambda s: s["hubs"][0].update(id="d"),
            lambda s: s["hubs"][0].update(accepts=[]),
            lambda s: s["hubs"][0].update(accepts=["produce", "produce"]),
            lambda s: s["hubs"][0].update(accepts=[{}]),
            lambda s: s["hubs"][0].update(cold_storage="false"),
            lambda s: s["hubs"][0].update(close_minute=10),
            lambda s: s.pop("name"),
        ]
        for mutation in mutations:
            scenario = tiny()
            mutation(scenario)
            with self.subTest(scenario=str(scenario)[:200]), self.assertRaises(ValidationError):
                validate(scenario)
        with self.assertRaises(ValidationError):
            validate(None)

    def test_untrusted_names_are_plain_data(self):
        scenario = tiny()
        scenario["name"] = "<script>alert(1)</script>"
        scenario["donors"][0]["name"] = "$(touch /tmp/not-a-command)"
        self.assertEqual(plan(scenario)["summary"]["allocated"], 10)

    def test_two_by_two_matches_exhaustive_integer_oracle(self):
        rng = random.Random(30408)
        for case in range(180):
            scenario = tiny()
            scenario.update(max_leg_km=rng.choice([2, 5, 15]), speed_kph=60)
            scenario["donors"] = [
                dict(scenario["donors"][0], id=f"d{i}", quantity=rng.randrange(4),
                     x_km=rng.randrange(8), y_km=rng.randrange(8),
                     category=rng.choice(["produce", "bakery"]))
                for i in range(2)
            ]
            scenario["hubs"] = [
                dict(scenario["hubs"][0], id=f"h{i}", demand=rng.randrange(4), capacity=rng.randrange(4),
                     x_km=rng.randrange(8), y_km=rng.randrange(8),
                     accepts=rng.choice([["produce"], ["bakery"], ["produce", "bakery"]]))
                for i in range(2)
            ]
            donors, hubs = scenario["donors"], scenario["hubs"]
            pairs = [eligibility(scenario, donor, hub) for donor in donors for hub in hubs]
            best = (0, 0)
            ranges = [range(min(donors[i // 2]["quantity"], hubs[i % 2]["demand"],
                                hubs[i % 2]["capacity"]) + 1) if pair["eligible"] else range(1)
                      for i, pair in enumerate(pairs)]
            for flows in itertools.product(*ranges):
                if any(sum(flows[i * 2:i * 2 + 2]) > donors[i]["quantity"] for i in range(2)):
                    continue
                if any(flows[i] + flows[i + 2] > min(hubs[i]["demand"], hubs[i]["capacity"]) for i in range(2)):
                    continue
                score = (sum(flows), -sum(flow * pair["cost_meters"] for flow, pair in zip(flows, pairs)))
                best = max(best, score)
            result = plan(scenario)
            with self.subTest(case=case):
                self.assertEqual((result["summary"]["allocated"], -round(result["summary"]["serving_km"] * 1000)), best)
                self.assertGreaterEqual(result["improvement"], 0)
                for transfer in result["transfers"]:
                    self.assertIs(type(transfer["quantity"]), int)

    def test_larger_random_network_conserves_every_capacity(self):
        rng = random.Random(42)
        scenario = tiny()
        scenario["max_leg_km"] = 30
        scenario["donors"] = [
            dict(scenario["donors"][0], id=f"d{i}", quantity=rng.randrange(10000),
                 x_km=rng.random() * 20, y_km=rng.random() * 20) for i in range(20)
        ]
        scenario["hubs"] = [
            dict(scenario["hubs"][0], id=f"h{i}", demand=rng.randrange(10000), capacity=rng.randrange(10000),
                 x_km=rng.random() * 20, y_km=rng.random() * 20) for i in range(20)
        ]
        result = plan(scenario)
        for donor in scenario["donors"]:
            self.assertLessEqual(sum(t["quantity"] for t in result["transfers"] if t["donor_id"] == donor["id"]), donor["quantity"])
        for hub in scenario["hubs"]:
            self.assertLessEqual(sum(t["quantity"] for t in result["transfers"] if t["hub_id"] == hub["id"]), min(hub["demand"], hub["capacity"]))
        self.assertEqual(sum(t["quantity"] for t in result["transfers"]), result["summary"]["allocated"])
        self.assertEqual(result["summary"]["allocated"], min(
            sum(d["quantity"] for d in scenario["donors"]),
            sum(min(h["demand"], h["capacity"]) for h in scenario["hubs"]),
        ))


if __name__ == "__main__":
    unittest.main()
