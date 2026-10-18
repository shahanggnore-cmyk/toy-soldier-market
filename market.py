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

def validate_offers(offers, config):
    errors, warnings = [], []
    required = ["seller_id", "seller_name", "product_id", "product_name", "unit_price", "quantity", "effective_day"]
    seen = set()
    max_price = float(config.get("max_unit_price", 100000))
    for i, row in enumerate(offers, start=2):
        for field in required:
            if not str(row.get(field, "")).strip():
                errors.append(f"Row {i}: missing required field '{field}'.")
        key = (str(row.get("seller_id", "")).strip(), str(row.get("product_id", "")).strip())
        if key in seen:
            warnings.append(f"Row {i}: duplicate seller/product pair {key}; the engine treats rows as separate offers.")
        seen.add(key)
        price = _number(row.get("unit_price"), "unit_price", errors, i, 0)
        quantity = _number(row.get("quantity"), "quantity", errors, i, 0)
        day = _number(row.get("effective_day"), "effective_day", errors, i, 1)
        if price is not None and price > max_price:
            errors.append(f"Row {i}: unit_price exceeds configured maximum {max_price}.")
        if quantity is not None and not quantity.is_integer():
            errors.append(f"Row {i}: quantity must be a whole number.")
        if day is not None and not day.is_integer():
            errors.append(f"Row {i}: effective_day must be a whole number.")
    return {"errors": errors, "warnings": warnings, "valid": not errors, "offer_count": len(offers)}

def _offer_id(row, index):
    return f"{row.get('seller_id','')}-{row.get('product_id','')}-{index}"

def _customer_population(config, rng):
    types = config.get("customer_types", [])
    count = int(config.get("customers_per_day", 30))
    customers = []
    total_weights = sum(max(0, float(t.get("weight", 1))) for t in types) or 1
    for i in range(count):
        roll = rng.random() * total_weights
        selected = types[-1] if types else {"name":"standard","weight":1,"budget":100,"price_sensitivity":1,"value_multiplier":1,"loyalty_bonus":0}
        cumulative = 0
        for t in types:
            cumulative += max(0, float(t.get("weight", 1)))
            if roll <= cumulative:
                selected = t
                break
        budget = float(selected.get("budget", 100))
        customers.append({
            "buyer_id": f"D{i+1:04d}",
            "type": selected.get("name", "standard"),
            "budget": budget,
            "price_sensitivity": float(selected.get("price_sensitivity", 1)),
            "value_multiplier": float(selected.get("value_multiplier", 1)),
            "loyalty_bonus": float(selected.get("loyalty_bonus", 0)),
            "preferred_seller": selected.get("preferred_seller", ""),
            "quantity_cap": int(selected.get("quantity_cap", 1)),
            "purchase_probability": float(selected.get("purchase_probability", 0.8)),
        })
    return customers

def _offer_stock(row, inventory, index):
    key = f"{row.get('seller_id')}::{row.get('product_id')}::{index}"
    if key in inventory:
        return int(inventory[key])
    try:
        return int(float(row.get("quantity", 0)))
    except (TypeError, ValueError):
        return 0

def run_market_day(offers, config, inventory, day, seed):
    rng = random.Random(seed)
    run_id = str(uuid.uuid4())[:8]
    before = dict(inventory)
    stock = dict(inventory)
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
        key = f"{row.get('seller_id')}::{row.get('product_id')}::{idx}"
        if key not in stock:
            stock[key] = initial_quantity
        offer_rows.append({**row, "_idx":idx, "_key":key, "_price":price})
    customers = _customer_population(config, rng)
    rng.shuffle(customers)
    transactions = []
    no_purchase = 0
    for customer in customers:
        if rng.random() > customer["purchase_probability"]:
            no_purchase += 1
            continue
        choices = []
        for offer in offer_rows:
            available = int(stock.get(offer["_key"], 0))
            if available <= 0:
                continue
            price = offer["_price"]
            if price < 0 or price > customer["budget"]:
                continue
            # Configurable utility model: perceived value less price, with optional seller loyalty bonus.
            product_values = config.get("product_values", {})
            base_value = float(product_values.get(offer.get("product_id", ""), config.get("default_product_value", 25)))
            perceived = base_value * customer["value_multiplier"]
            loyalty = customer["loyalty_bonus"] if customer["preferred_seller"] == offer.get("seller_id") else 0
            utility = perceived - price * customer["price_sensitivity"] + loyalty
            if utility >= float(config.get("minimum_utility", 0)):
                choices.append((utility, offer))
        if not choices:
            no_purchase += 1
            continue
        # Random tie-break among exact utility matches; stable seed makes it reproducible.
        best_utility = max(x[0] for x in choices)
        best = [o for u, o in choices if abs(u-best_utility) < 1e-9]
        chosen = rng.choice(best)
        qty = min(int(stock[chosen["_key"]]), customer["quantity_cap"], max(1, int(customer["budget"] // chosen["_price"])) if chosen["_price"] > 0 else customer["quantity_cap"])
        if qty <= 0:
            no_purchase += 1
            continue
        total = round(qty * chosen["_price"], 2)
        stock[chosen["_key"]] -= qty
        transactions.append({
            "run_id": run_id, "day": day, "seed": seed, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "buyer_id": customer["buyer_id"], "buyer_type": customer["type"],
            "seller_id": chosen.get("seller_id"), "seller_name": chosen.get("seller_name"),
            "product_id": chosen.get("product_id"), "product_name": chosen.get("product_name"),
            "quantity": qty, "unit_price": round(chosen["_price"], 2), "total_price": total,
            "utility": round(best_utility, 4), "remaining_offer_stock": stock[chosen["_key"]]
        })
    units = sum(int(t["quantity"]) for t in transactions)
    revenue = sum(float(t["total_price"]) for t in transactions)
    return {
        "run_id": run_id, "day": day, "seed": seed, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "buyers": len(customers), "transactions": transactions, "transaction_count": len(transactions),
        "no_purchase_count": no_purchase, "units_sold": units, "revenue": round(revenue, 2),
        "inventory_before": before, "inventory_after": stock,
        "offer_file_sha256": hashlib.sha256(json.dumps(offers, sort_keys=True).encode()).hexdigest(),
        "rules_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
    }

def aggregate_transactions(transactions):
    sellers = {}
    products = {}
    for t in transactions:
        s = t.get("seller_id", "unknown")
        p = t.get("product_id", "unknown")
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

def replay_runs(offers, config, inventory, seed_a, seed_b):
    a = run_market_day(offers, config, inventory, day=1, seed=seed_a)
    b = run_market_day(offers, config, inventory, day=1, seed=seed_b)
    summary_a = {"transactions":a["transaction_count"],"units_sold":a["units_sold"],"revenue":a["revenue"]}
    summary_b = {"transactions":b["transaction_count"],"units_sold":b["units_sold"],"revenue":b["revenue"]}
    return {
        "replay_id": str(uuid.uuid4())[:8], "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seed_a": seed_a, "seed_b": seed_b, "summary_a": summary_a, "summary_b": summary_b,
        "transactions_a": a["transactions"], "transactions_b": b["transactions"],
        "inventory_note": "Both runs use the same starting inventory and are comparison-only; neither changes the live market state."
    }
