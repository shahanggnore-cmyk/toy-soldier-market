import csv
import json
import tempfile
import unittest
from pathlib import Path

from market import (
    run_market_day, validate_offers, recommend_buys, replay_runs,
    public_transaction, aggregate_transactions
)

class MarketEngineTests(unittest.TestCase):
    def setUp(self):
        self.offers = [
            {"offer_id":"A-TS01-D1","seller_id":"A","seller_name":"Seller A","product_id":"TS01","product_name":"Soldier","unit_price":"10","quantity":"2","effective_day":"1","eligible_customer_types":"","published_at":"2026-10-20T10:00:00-04:00"},
            {"offer_id":"B-TS01-D1","seller_id":"B","seller_name":"Seller B","product_id":"TS01","product_name":"Soldier","unit_price":"10","quantity":"2","effective_day":"1","eligible_customer_types":"","published_at":"2026-10-20T10:00:00-04:00"},
        ]
        self.config = {
            "customers_per_day": 12, "returning_customer_fraction": 0.5,
            "default_seed": 7, "max_unit_price": 100, "default_product_value": 20,
            "minimum_utility": 0, "switching_cost": 0.25,
            "product_values": {"TS01": 20},
            "customer_types": [
                {"name":"bargain_hunter","weight":1,"budget":10,"product_values":{"TS01":9},"quantity_cap":1,"purchase_probability":1,"search_limit":99,"inconvenience_cost":0,"loyalty_bonus":0},
                {"name":"collector","weight":1,"budget":30,"product_values":{"TS01":18},"quantity_cap":1,"purchase_probability":1,"search_limit":99,"inconvenience_cost":0,"loyalty_bonus":0.5},
                {"name":"convenience_shopper","weight":1,"budget":20,"product_values":{"TS01":12},"quantity_cap":1,"purchase_probability":1,"search_limit":1,"inconvenience_cost":0.25,"loyalty_bonus":0.25},
            ]
        }

    def test_offer_validation_requires_stable_id_and_timestamp(self):
        self.assertTrue(validate_offers(self.offers, self.config)["valid"])
        bad = [dict(self.offers[0], offer_id="", published_at="yesterday")]
        result = validate_offers(bad, self.config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("offer_id" in error for error in result["errors"]))
        self.assertTrue(any("ISO-8601" in error for error in result["errors"]))

    def test_recommendation_never_exceeds_target_or_stock(self):
        offers = [dict(o, quantity="10") for o in self.offers]
        recs = recommend_buys(offers, self.config, target_units=3, qualities={"0":9,"1":5}, quality_weight=75)
        self.assertEqual(sum(r["recommended_quantity"] for r in recs), 3)
        self.assertTrue(all(r["recommended_quantity"] <= r["available_quantity"] for r in recs))
        self.assertEqual(recs[0]["seller_id"], "A")

    def test_customer_can_buy_nothing_when_utility_is_not_positive(self):
        offer = [dict(self.offers[0], unit_price="10", quantity="1")]
        config = {
            "customers_per_day": 1, "returning_customer_fraction": 0,
            "minimum_utility": 0, "default_product_value": 9,
            "product_values": {"TS01": 9},
            "customer_types": [{"name":"bargain_hunter","weight":1,"budget":10,
                "product_values":{"TS01":9},"quantity_cap":1,"purchase_probability":1,
                "search_limit":99,"inconvenience_cost":0,"loyalty_bonus":0}],
        }
        result = run_market_day(offer, config, {}, 1, 9)
        self.assertEqual(result["transactions"], [])
        self.assertEqual(result["no_purchase_count"], 1)
        self.assertEqual(result["inventory_after"]["A-TS01-D1"], 1)

    def test_lower_price_does_not_reduce_utility(self):
        offer = [dict(self.offers[0], unit_price="10", quantity="2")]
        config = {
            "customers_per_day": 1, "returning_customer_fraction": 0,
            "minimum_utility": 0, "default_product_value": 20,
            "product_values": {"TS01": 20},
            "customer_types": [{"name":"collector","weight":1,"budget":30,
                "product_values":{"TS01":20},"quantity_cap":1,"purchase_probability":1,
                "search_limit":99,"inconvenience_cost":0,"loyalty_bonus":0}],
        }
        expensive = run_market_day(offer, config, {}, 1, 11)
        cheaper_offer = [dict(offer[0], unit_price="8")]
        cheaper = run_market_day(cheaper_offer, config, {}, 1, 11)
        self.assertEqual(len(expensive["transactions"]), 1)
        self.assertEqual(len(cheaper["transactions"]), 1)
        self.assertGreater(cheaper["transactions"][0]["utility"], expensive["transactions"][0]["utility"])

    def test_simulation_respects_stock_budget_and_one_purchase_per_customer(self):
        result = run_market_day(self.offers, self.config, {}, 1, 17)
        self.assertLessEqual(result["units_sold"], 4)
        self.assertTrue(all(v >= 0 for v in result["inventory_after"].values()))
        buyer_ids = [t["buyer_id"] for t in result["transactions"]]
        self.assertEqual(len(buyer_ids), len(set(buyer_ids)))
        profiles = result["customer_profiles_after"]
        for t in result["transactions"]:
            self.assertLessEqual(t["total_price"], profiles[t["buyer_id"]]["budget"])
        self.assertEqual(result["buyers"], result["transaction_count"] + result["no_purchase_count"])

    def test_same_seed_and_starting_state_reproduces_allocations(self):
        a = run_market_day(self.offers, self.config, {}, 1, 123)
        b = run_market_day(self.offers, self.config, {}, 1, 123)
        compact = lambda r: [(t["buyer_id"],t["seller_id"],t["product_id"],t["quantity"],t["total_price"]) for t in r["transactions"]]
        self.assertEqual(compact(a), compact(b))
        self.assertEqual(a["inventory_after"], b["inventory_after"])

    def test_replay_does_not_mutate_starting_state(self):
        inventory = {"A-TS01-D1":1}
        profiles = {"C00001":{"buyer_id":"C00001","type":"collector","budget":30,"product_values":{"TS01":18},"value_multiplier":1,"loyalty_bonus":0.5,"quantity_cap":1,"purchase_probability":1,"search_limit":99,"inconvenience_cost":0,"preferred_product_ids":[],"advertising_lift":0}}
        history = {"C00001":{"A":1}}
        before = json.dumps([inventory, profiles, history], sort_keys=True)
        replay_runs(self.offers, self.config, inventory, 10, 20, profiles, history, day=1)
        self.assertEqual(json.dumps([inventory, profiles, history], sort_keys=True), before)


    def test_bundle_purchase_deducts_every_component(self):
        offers = [
            {"offer_id":"A-TS01-D1","seller_id":"A","seller_name":"Seller A","product_id":"TS01","product_name":"Soldier","unit_price":"5","quantity":"5","effective_day":"1","eligible_customer_types":"","bundle_components":"","published_at":"2026-10-20T10:00:00-04:00"},
            {"offer_id":"A-TS02-D1","seller_id":"A","seller_name":"Seller A","product_id":"TS02","product_name":"Flag","unit_price":"3","quantity":"3","effective_day":"1","eligible_customer_types":"","bundle_components":"","published_at":"2026-10-20T10:00:00-04:00"},
            {"offer_id":"A-SET-D1","seller_id":"A","seller_name":"Seller A","product_id":"SET01","product_name":"Collector Set","unit_price":"20","quantity":"2","effective_day":"1","eligible_customer_types":"","bundle_components":"TS01:2;TS02:1","published_at":"2026-10-20T10:00:00-04:00"},
        ]
        config = {
            "customers_per_day":1, "returning_customer_fraction":0,
            "default_product_value":1, "minimum_utility":0,
            "product_values":{"TS01":1,"TS02":1,"SET01":50},
            "customer_types":[{"name":"collector","weight":1,"budget":30,
                "product_values":{"TS01":1,"TS02":1,"SET01":50},
                "quantity_cap":1,"purchase_probability":1,"search_limit":99,
                "inconvenience_cost":0,"loyalty_bonus":0,"preferred_product_ids":[]}],
        }
        self.assertTrue(validate_offers(offers, config)["valid"])
        result=run_market_day(offers,config,{},1,44)
        self.assertEqual(len(result["transactions"]),1)
        transaction=result["transactions"][0]
        self.assertEqual(transaction["product_id"],"SET01")
        self.assertEqual(transaction["component_units_deducted"],{"TS01":2,"TS02":1})
        self.assertEqual(result["inventory_after"]["A-TS01-D1"],3)
        self.assertEqual(result["inventory_after"]["A-TS02-D1"],2)
        self.assertEqual(result["inventory_after"]["A-SET-D1"],1)

    def test_strategy_replay_changes_only_selected_seller_and_preserves_state(self):
        inventory = {}
        result = replay_runs(
            self.offers, self.config, inventory, 321, 321,
            strategy_seller_id="A", multiplier_a=1.0, multiplier_b=0.8, day=1
        )
        self.assertEqual(result["seed_a"], result["seed_b"])
        self.assertEqual(result["strategy_seller_id"], "A")
        self.assertEqual(result["multiplier_a"], 1.0)
        self.assertEqual(result["multiplier_b"], 0.8)
        self.assertEqual(inventory, {})
        self.assertIn("Competitor prices are held fixed", result["inventory_note"])

    def test_invalid_bundle_component_is_rejected(self):
        offer = dict(self.offers[0], bundle_components="MISSING:1")
        result = validate_offers([offer], self.config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("no offer/inventory row" in error for error in result["errors"]))

    def test_public_transaction_omits_private_customer_fields(self):
        row = {"buyer_id":"C00001","buyer_type":"collector","utility":8.5,"remaining_budget":20,"seller_id":"A","quantity":1}
        public = public_transaction(row)
        self.assertNotIn("buyer_id", public)
        self.assertNotIn("buyer_type", public)
        self.assertNotIn("utility", public)
        self.assertNotIn("remaining_budget", public)

if __name__ == "__main__":
    unittest.main()
