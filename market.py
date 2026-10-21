from datetime import datetime, timezone
from pathlib import Path
import json, hashlib, random, uuid, csv

def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with p.open(encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)

def append_jsonl(path, row):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")

def load_config(data_dir):
    return load_json(Path(data_dir) / "rules.json", {})

def _number(value, field, errors, row_num, minimum=None):
    try:
        x = float(value)
        if minimum is not None and x < minimum:
            errors.append(f"Row {row_num}: {field} must be at least {minimum}.")
        return x
    except (TypeError, ValueError):
        errors.append(f"Row {row_num}: {field} must be numeric.")
        return None

def _parse_bundle_components(raw):
    """Parse `PRODUCT_ID:COUNT;PRODUCT_ID:COUNT`; blank means a single-product offer."""
    components = {}
    raw = str(raw or "").strip()
    if not raw:
        return components
    for part in raw.split(";"):
        if ":" not in part:
            raise ValueError("bundle_components must use PRODUCT_ID:COUNT entries separated by semicolons.")
        product_id, count = part.split(":", 1)
        product_id = product_id.strip()
        try:
            count_value = int(count.strip())
        except ValueError as exc:
            raise ValueError("bundle component counts must be positive whole numbers.") from exc
        if not product_id or count_value < 1:
            raise ValueError("bundle component IDs must be non-empty and counts must be positive.")
        components[product_id] = components.get(product_id, 0) + count_value
    return components

def validate_offers(offers, config):
    errors, warnings = [], []
    required = ["offer_id", "seller_id", "seller_name", "product_id", "product_name", "unit_price", "quantity", "effective_day", "published_at"]
    seen_ids = set()
    max_price = float(config.get("max_unit_price", 100000))
    for i, row in enumerate(offers, start=2):
        for field in required:
            if not str(row.get(field, "")).strip():
                errors.append(f"Row {i}: missing required field '{field}'.")
        offer_id = str(row.get("offer_id", "")).strip()
        if offer_id and offer_id in seen_ids:
            errors.append(f"Row {i}: duplicate offer_id '{offer_id}'.")
        if offer_id:
            seen_ids.add(offer_id)
        price = _number(row.get("unit_price"), "unit_price", errors, i, 0)
        quantity = _number(row.get("quantity"), "quantity", errors, i, 0)
        day = _number(row.get("effective_day"), "effective_day", errors, i, 1)
        if price is not None and price > max_price:
            errors.append(f"Row {i}: unit_price exceeds configured maximum {max_price}.")
        if quantity is not None and not quantity.is_integer():
            errors.append(f"Row {i}: quantity must be a whole number.")
        if day is not None and not day.is_integer():
            errors.append(f"Row {i}: effective_day must be a whole number.")
        published_at = str(row.get("published_at", "")).strip()
        if published_at:
            try:
                parsed_timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                if parsed_timestamp.tzinfo is None:
                    errors.append(f"Row {i}: published_at must include a timezone offset.")
            except ValueError:
                errors.append(f"Row {i}: published_at must be an ISO-8601 timestamp with timezone.")
        try:
            _parse_bundle_components(row.get("bundle_components", ""))
        except ValueError as exc:
            errors.append(f"Row {i}: {exc}")
    available_products = {(str(o.get("seller_id", "")).strip(), str(o.get("product_id", "")).strip()) for o in offers}
    for i, row in enumerate(offers, start=2):
        try:
            components = _parse_bundle_components(row.get("bundle_components", ""))
        except ValueError:
            continue
        for product_id in components:
            if (str(row.get("seller_id", "")).strip(), product_id) not in available_products:
                errors.append(f"Row {i}: bundle component '{product_id}' has no offer/inventory row for this seller.")
    return {"errors": errors, "warnings": warnings, "valid": not errors, "offer_count": len(offers)}

def _offer_key(row, index):
    # Prefer a stable explicit offer_id; fallback is stable row identity for legacy CSVs.
    return str(row.get("offer_id") or f"{row.get('seller_id','')}::{row.get('product_id','')}::{index}")

def _new_customer(customer_id, customer_type):
    return {
        "buyer_id": customer_id,
        "type": customer_type.get("name", "standard"),
        "budget": float(customer_type.get("budget", 100)),
        "product_values": dict(customer_type.get("product_values", {})),
        "value_multiplier": float(customer_type.get("value_multiplier", 1)),
        "loyalty_bonus": float(customer_type.get("loyalty_bonus", 0)),
        "quantity_cap": max(1, int(customer_type.get("quantity_cap", 1))),
        "purchase_probability": min(1.0, max(0.0, float(customer_type.get("purchase_probability", 1)))),
        "search_limit": max(1, int(customer_type.get("search_limit", 999999))),
        "inconvenience_cost": max(0.0, float(customer_type.get("inconvenience_cost", 0))),
        "preferred_product_ids": list(customer_type.get("preferred_product_ids", [])),
        "advertising_lift": min(1.0, max(0.0, float(customer_type.get("advertising_lift", 0)))),
    }

def _customer_population(config, rng, customer_profiles=None):
    """Return daily customers plus updated private profiles.

    Returning customers keep their type and ID; their daily budget renews according
    to this classroom model. Profiles remain in private state and never in public exports.
    """
    types = config.get("customer_types", [])
    count = max(0, int(config.get("customers_per_day", 30)))
    if not types:
        types = [{"name": "standard", "weight": 1, "budget": 100,
                  "product_values": {}, "value_multiplier": 1}]
    weights = [max(0.0, float(t.get("weight", 1))) for t in types]
    if sum(weights) <= 0:
        weights = [1.0] * len(types)
    existing = list((customer_profiles or {}).values())
    returning_fraction = min(1.0, max(0.0, float(config.get("returning_customer_fraction", 0.5))))
    returning_count = min(len(existing), int(round(count * returning_fraction))) if existing else 0
    returning = rng.sample(existing, returning_count) if returning_count else []
    customers = []
    updated_profiles = dict(customer_profiles or {})
    for profile in returning:
        c = dict(profile)
        # Budget renewal is an explicit daily model rule.
        c["budget_remaining"] = float(c["budget"])
        customers.append(c)
    next_num = max([int(str(k).replace("C", "")) for k in updated_profiles if str(k).startswith("C") and str(k)[1:].isdigit()] or [0]) + 1
    for _ in range(count - len(returning)):
        chosen = rng.choices(types, weights=weights, k=1)[0]
        c = _new_customer(f"C{next_num:05d}", chosen)
        next_num += 1
        c["budget_remaining"] = float(c["budget"])
        updated_profiles[c["buyer_id"]] = dict(c)
        customers.append(c)
    for c in customers:
        updated_profiles[c["buyer_id"]] = {k: v for k, v in c.items() if k != "budget_remaining"}
    rng.shuffle(customers)
    return customers, updated_profiles

def _customer_value(customer, offer, config):
    product_id = str(offer.get("product_id", ""))
    # Type-specific explicit values override the global fallback model.
    if product_id in customer.get("product_values", {}):
        value = float(customer["product_values"][product_id])
    else:
        value = float(config.get("product_values", {}).get(
            product_id, config.get("default_product_value", 25)
        )) * float(customer.get("value_multiplier", 1))
    if customer.get("preferred_product_ids") and product_id in customer["preferred_product_ids"]:
        value += float(config.get("preferred_product_bonus", 0))
    return value

def run_market_day(offers, config, inventory, day, seed, customer_profiles=None, customer_history=None):
    """Run one virtual market day. Never reads or modifies physical seller stock."""
    rng = random.Random(seed)
    # Keep tie-breaking on a separate deterministic stream so a pricing change
    # cannot shift the later customers' search/order random draws.
    tie_rng = random.Random(seed ^ 0x9E3779B9)
    run_id = str(uuid.uuid4())[:8]
    before = dict(inventory or {})
    stock = dict(inventory or {})
    offer_rows = []
    for idx, row in enumerate(offers):
        try:
            effective_day = int(float(row.get("effective_day", 1)))
            price = float(row.get("unit_price", 0))
            initial_quantity = int(float(row.get("quantity", 0)))
        except (ValueError, TypeError):
            continue
        if effective_day > day:
            continue
        key = _offer_key(row, idx)
        if key not in stock:
            stock[key] = initial_quantity
        offer_rows.append({**row, "_idx": idx, "_key": key, "_price": price})
    # Build component inventory lookup for bundles; component stock is shared
    # with the seller's single-product offers and cannot be deducted twice.
    component_rows = {}
    for offer in offer_rows:
        component_rows.setdefault((str(offer.get("seller_id", "")), str(offer.get("product_id", ""))), []).append(offer)
    # Include first-day offer stock in the recorded opening ledger.
    before = dict(stock)
    profiles = customer_profiles or {}
    history = {k: dict(v) for k, v in (customer_history or {}).items()}
    customers, profiles_after = _customer_population(config, rng, profiles)
    # One purchase maximum per customer is enforced by processing each customer once.
    transactions = []
    no_purchase = 0
    ad = config.get("advertising", {}) or {}
    ad_seller = str(ad.get("seller_id", ""))
    ad_lift = min(1.0, max(0.0, float(ad.get("consideration_probability_lift", 0))))
    for customer in customers:
        if rng.random() > customer["purchase_probability"]:
            no_purchase += 1
            continue
        # Customers inspect a limited, randomized subset of sellers if their type has limited search.
        seller_ids = list(dict.fromkeys(o.get("seller_id", "") for o in offer_rows))
        rng.shuffle(seller_ids)
        visible_sellers = set(seller_ids[:customer["search_limit"]])
        if ad_seller and ad_lift > 0 and rng.random() < ad_lift:
            visible_sellers.add(ad_seller)
        choices = []
        for offer in offer_rows:
            if offer.get("seller_id", "") not in visible_sellers:
                continue
            available = int(stock.get(offer["_key"], 0))
            if available <= 0:
                continue
            try:
                bundle_components = _parse_bundle_components(offer.get("bundle_components", ""))
            except ValueError:
                continue
            component_capacity = available
            components_available = True
            for component_id, units_per_bundle in bundle_components.items():
                component_offers = component_rows.get((str(offer.get("seller_id", "")), component_id), [])
                component_stock = sum(int(stock.get(component["_key"], 0)) for component in component_offers)
                if component_stock < units_per_bundle:
                    components_available = False
                    break
                component_capacity = min(component_capacity, component_stock // units_per_bundle)
            if not components_available:
                continue
            price = offer["_price"]
            if price < 0 or price > float(customer.get("budget_remaining", customer["budget"])):
                continue
            # Optional eligibility fields: eligible_customer_types is a semicolon-separated list.
            eligible = str(offer.get("eligible_customer_types", "")).strip()
            if eligible and customer["type"] not in {x.strip() for x in eligible.split(";")}:
                continue
            value = _customer_value(customer, offer, config)
            seller_history = history.get(customer["buyer_id"], {})
            previous_count = int(seller_history.get(offer.get("seller_id", ""), 0))
            loyalty = float(customer.get("loyalty_bonus", 0)) if previous_count > 0 else 0.0
            # Inconvenience is explicit and may be increased for sellers not in a customer's known history.
            inconvenience = float(customer.get("inconvenience_cost", 0))
            if config.get("switching_cost", 0) and seller_history and previous_count == 0:
                inconvenience += float(config.get("switching_cost", 0))
            # Advertising only changes consideration, never utility or purchase guarantee.
            utility = value - price + loyalty - inconvenience
            if utility > float(config.get("minimum_utility", 0)):
                choices.append((utility, offer))
        if not choices:
            no_purchase += 1
            continue
        best_utility = max(x[0] for x in choices)
        best = [o for u, o in choices if abs(u - best_utility) < 1e-9]
        chosen = tie_rng.choice(best)
        available = int(stock[chosen["_key"]])
        price = float(chosen["_price"])
        bundle_components = _parse_bundle_components(chosen.get("bundle_components", ""))
        qty = min(available, int(customer["quantity_cap"]))
        for component_id, units_per_bundle in bundle_components.items():
            component_offers = component_rows.get((str(chosen.get("seller_id", "")), component_id), [])
            component_stock = sum(int(stock.get(component["_key"], 0)) for component in component_offers)
            qty = min(qty, component_stock // units_per_bundle)
        # One purchase can be a single item or one/more advertised bundles; never exceed budget.
        if price > 0:
            qty = min(qty, int(float(customer.get("budget_remaining", customer["budget"])) // price))
        if qty <= 0:
            no_purchase += 1
            continue
        total = round(qty * price, 2)
        stock[chosen["_key"]] -= qty
        component_deductions = {}
        for component_id, units_per_bundle in bundle_components.items():
            remaining_component_units = qty * units_per_bundle
            component_offers = component_rows.get((str(chosen.get("seller_id", "")), component_id), [])
            for component in component_offers:
                take = min(remaining_component_units, int(stock.get(component["_key"], 0)))
                if take:
                    stock[component["_key"]] -= take
                    remaining_component_units -= take
                if remaining_component_units <= 0:
                    break
            component_deductions[component_id] = qty * units_per_bundle
        customer["budget_remaining"] = round(float(customer.get("budget_remaining", customer["budget"])) - total, 2)
        history.setdefault(customer["buyer_id"], {})
        history[customer["buyer_id"]][chosen.get("seller_id", "")] = int(history[customer["buyer_id"]].get(chosen.get("seller_id", ""), 0)) + 1
        transactions.append({
            "run_id": run_id, "day": day, "seed": seed, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "buyer_id": customer["buyer_id"], "buyer_type": customer["type"],
            "seller_id": chosen.get("seller_id"), "seller_name": chosen.get("seller_name"),
            "product_id": chosen.get("product_id"), "product_name": chosen.get("product_name"),
            "offer_id": chosen.get("offer_id") or chosen["_key"],
            "bundle_components": chosen.get("bundle_components", ""),
            "component_units_deducted": component_deductions,
            "quantity": qty, "unit_price": round(price, 2), "total_price": total,
            "utility": round(best_utility, 4), "remaining_offer_stock": stock[chosen["_key"]],
            "remaining_budget": customer["budget_remaining"],
        })
    units = sum(int(t["quantity"]) for t in transactions)
    revenue = sum(float(t["total_price"]) for t in transactions)
    return {
        "run_id": run_id, "day": day, "seed": seed, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "buyers": len(customers), "transactions": transactions, "transaction_count": len(transactions),
        "no_purchase_count": no_purchase, "units_sold": units, "revenue": round(revenue, 2),
        "inventory_before": before, "inventory_after": stock,
        "customer_profiles_after": profiles_after, "customer_history_after": history,
        "offer_file_sha256": hashlib.sha256(json.dumps(offers, sort_keys=True).encode()).hexdigest(),
        "rules_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
    }

def aggregate_transactions(transactions):
    sellers, products = {}, {}
    for t in transactions:
        s, p = t.get("seller_id", "unknown"), t.get("product_id", "unknown")
        sellers.setdefault(s, {"seller_id":s, "seller_name":t.get("seller_name", s), "transactions":0, "units":0, "revenue":0.0})
        sellers[s]["transactions"] += 1
        sellers[s]["units"] += int(t.get("quantity", 0))
        sellers[s]["revenue"] += float(t.get("total_price", 0))
        products.setdefault(p, {"product_id":p, "product_name":t.get("product_name", p), "transactions":0, "units":0, "revenue":0.0})
        products[p]["transactions"] += 1
        products[p]["units"] += int(t.get("quantity", 0))
        products[p]["revenue"] += float(t.get("total_price", 0))
    for group in (sellers, products):
        for row in group.values():
            row["revenue"] = round(row["revenue"], 2)
    return {
        "transaction_count": len(transactions),
        "units_sold": sum(int(t.get("quantity", 0)) for t in transactions),
        "revenue": round(sum(float(t.get("total_price", 0)) for t in transactions), 2),
        "by_seller": sorted(sellers.values(), key=lambda x:x["seller_id"]),
        "by_product": sorted(products.values(), key=lambda x:x["product_id"]),
    }

def public_transaction(transaction):
    """Remove individual customer identity, type, private utility and budget from public output."""
    private = {"buyer_id", "buyer_type", "utility", "remaining_budget", "seed"}
    return {k: v for k, v in transaction.items() if k not in private}

def public_run(run, publish_seed=False):
    """Return public aggregate fields; omit exact seeds unless explicitly approved."""
    allowed = ("run_id", "day", "timestamp_utc", "transactions", "buyers",
               "units_sold", "revenue", "no_purchase_count",
               "inventory_before", "inventory_after")
    result = {k: run[k] for k in allowed if k in run}
    if publish_seed and "seed" in run:
        result["seed"] = run["seed"]
    return result

def replay_runs(offers, config, inventory, seed_a, seed_b, customer_profiles=None,
                customer_history=None, day=1, strategy_seller_id=None,
                multiplier_a=1.0, multiplier_b=1.0):
    """Compare two price strategies from the same starting state and customer draws.

    Only the selected seller's price is adjusted. All competitor offers remain fixed.
    Passing the same seed for A and B ensures common customer draws/order/tie-break stream.
    """
    multiplier_a = float(multiplier_a)
    multiplier_b = float(multiplier_b)
    if not (0 < multiplier_a <= 10 and 0 < multiplier_b <= 10):
        raise ValueError("Price multipliers must be greater than 0 and at most 10.")
    base_offers = [dict(row) for row in offers]
    def adjusted(multiplier):
        result = [dict(row) for row in base_offers]
        for row in result:
            if not strategy_seller_id or str(row.get("seller_id", "")) == str(strategy_seller_id):
                row["unit_price"] = str(round(float(row["unit_price"]) * multiplier, 2))
        return result
    offers_a, offers_b = adjusted(multiplier_a), adjusted(multiplier_b)
    start_inventory = dict(inventory or {})
    start_profiles = dict(customer_profiles or {})
    start_history = dict(customer_history or {})
    a = run_market_day(offers_a, config, dict(start_inventory), day, seed_a,
                       start_profiles, start_history)
    b = run_market_day(offers_b, config, dict(start_inventory), day, seed_b,
                       start_profiles, start_history)
    summary_a = {"transactions":a["transaction_count"],"units_sold":a["units_sold"],
                 "revenue":a["revenue"],"no_purchase_count":a["no_purchase_count"]}
    summary_b = {"transactions":b["transaction_count"],"units_sold":b["units_sold"],
                 "revenue":b["revenue"],"no_purchase_count":b["no_purchase_count"]}
    return {
        "replay_id": str(uuid.uuid4())[:8], "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seed_a": seed_a, "seed_b": seed_b, "strategy_seller_id": strategy_seller_id or "ALL",
        "multiplier_a": multiplier_a, "multiplier_b": multiplier_b,
        "summary_a": summary_a, "summary_b": summary_b,
        "transactions_a": [public_transaction(t) for t in a["transactions"]],
        "transactions_b": [public_transaction(t) for t in b["transactions"]],
        "inventory_after_a": a["inventory_after"], "inventory_after_b": b["inventory_after"],
        "inventory_note": "Both runs use independent copies of the same starting inventory, customer profiles, and histories. Competitor prices are held fixed when a seller is selected. Neither run changes the live market state."
    }

def recommend_buys(offers, config, target_units=None, qualities=None, quality_weight=60):
    """Supplementary offer-ranking tool; never modifies the simulation ledger."""
    qualities = qualities or {}
    target = max(0, int(target_units or 0))
    quality_weight = min(100, max(0, int(quality_weight)))
    recommendations = []
    valid = []
    for index, offer in enumerate(offers):
        try:
            price = float(offer["unit_price"])
            quantity = max(0, int(float(offer["quantity"])))
            quality = int(qualities.get(str(index), qualities.get(str(offer.get("offer_id", "")), 5)))
            if price < 0 or quantity < 0 or not 1 <= quality <= 10:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if quantity == 0:
            continue
        valid.append((index, offer, price, quantity, quality))
    if not valid:
        return []
    cheapest = min(x[2] for x in valid if x[2] > 0) if any(x[2] > 0 for x in valid) else 0
    for index, offer, price, quantity, quality in valid:
        qscore = quality * 10
        pscore = (cheapest / price * 100) if price > 0 and cheapest > 0 else (100 if price == 0 else 0)
        score = qscore * quality_weight / 100 + pscore * (100-quality_weight) / 100
        recommendations.append({
            "index": index, "seller_id": offer.get("seller_id", ""),
            "seller_name": offer.get("seller_name", ""), "product_id": offer.get("product_id", ""),
            "product_name": offer.get("product_name", ""), "unit_price": price,
            "available_quantity": quantity, "quality": quality, "score": round(score, 1),
            "recommended_quantity": 0,
        })
    recommendations.sort(key=lambda x: (-x["score"], x["unit_price"], x["seller_id"]))
    remaining = target
    for item in recommendations:
        quantity = min(remaining, item["available_quantity"])
        item["recommended_quantity"] = quantity
        remaining -= quantity
    return recommendations
