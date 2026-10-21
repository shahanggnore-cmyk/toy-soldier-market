from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, abort
from pathlib import Path
from datetime import datetime, timezone
import json, csv, io, os
from market import (
    load_config, run_market_day, validate_offers, load_json, save_json,
    append_jsonl, aggregate_transactions, replay_runs, public_transaction, public_run
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-development-key-change-before-deploy")

def get_state():
    return load_json(DATA / "state.json", {
        "day": 0, "inventory": {}, "transactions": [], "runs": [],
        "customer_profiles": {}, "customer_history": {}
    })

def get_offers():
    path = DATA / "offers.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def _public_state_summary(state):
    config = load_config(DATA)
    publish_seed = bool(config.get("publish_seed", False))
    return {
        "day": state.get("day", 0),
        "aggregate": aggregate_transactions(state.get("transactions", [])),
        "runs": [public_run(r, publish_seed=publish_seed) for r in state.get("runs", [])],
        "inventory": state.get("inventory", {}),
    }

@app.route("/")
def index():
    config = load_config(DATA)
    state = get_state()
    offers = get_offers()
    validation = validate_offers(offers, config)
    aggregate = aggregate_transactions(state.get("transactions", []))
    sellers = load_json(DATA / "sellers.json", [])
    announcements = load_json(DATA / "announcements.json", [])
    latest = state.get("runs", [])[-1] if state.get("runs") else None
    return render_template(
        "index.html", config=config, state=state, offers=offers,
        validation=validation, aggregate=aggregate, sellers=sellers,
        announcements=announcements, latest=latest,
        demo_mode=os.environ.get("MARKET_MODE", "demo").lower() == "demo"
    )

@app.route("/run", methods=["POST"])
def run_day():
    # This starter runs in demo mode by default. Set MARKET_MODE=live and
    # ADMIN_TOKEN before opening a scored market; live mutations require the token.
    if os.environ.get("MARKET_MODE", "demo").lower() == "live":
        expected = os.environ.get("ADMIN_TOKEN", "")
        supplied = request.form.get("admin_token", "")
        if not expected or supplied != expected:
            abort(403, "Authorized market operator token required.")
    config = load_config(DATA)
    offers = get_offers()
    validation = validate_offers(offers, config)
    if validation["errors"]:
        flash("Simulation stopped: fix the offer-file errors shown below first.", "error")
        return redirect(url_for("index"))
    state = get_state()
    day = int(state.get("day", 0)) + 1
    seed_raw = request.form.get("seed", "").strip()
    try:
        seed = int(seed_raw) if seed_raw else int(config.get("default_seed", 2026)) + day
    except ValueError:
        flash("Seed must be a whole number.", "error")
        return redirect(url_for("index"))
    result = run_market_day(
        offers, config, state.get("inventory", {}), day, seed,
        state.get("customer_profiles", {}), state.get("customer_history", {})
    )
    state["day"] = day
    state["inventory"] = result["inventory_after"]
    state["customer_profiles"] = result["customer_profiles_after"]
    state["customer_history"] = result["customer_history_after"]
    state.setdefault("transactions", []).extend(result["transactions"])
    # Store only public-safe summary fields in the run list. Private profiles remain
    # in the protected local state and are never placed in public results downloads.
    state.setdefault("runs", []).append({
        "run_id": result["run_id"], "day": day, "seed": seed,
        "timestamp_utc": result["timestamp_utc"],
        "transactions": result["transaction_count"], "buyers": result["buyers"],
        "units_sold": result["units_sold"], "revenue": result["revenue"],
        "no_purchase_count": result["no_purchase_count"],
        "inventory_before": result["inventory_before"],
        "inventory_after": result["inventory_after"],
    })
    save_json(DATA / "state.json", state)
    append_jsonl(DATA / "audit.jsonl", {
        "event": "market_day_completed", "run_id": result["run_id"], "day": day,
        "seed": seed, "timestamp_utc": result["timestamp_utc"],
        "offer_count": len(offers), "transaction_count": result["transaction_count"],
        "units_sold": result["units_sold"], "revenue": result["revenue"],
        "no_purchase_count": result["no_purchase_count"],
        "inventory_before": result["inventory_before"],
        "inventory_after": result["inventory_after"],
        "offer_file_sha256": result["offer_file_sha256"],
        "rules_sha256": result["rules_sha256"],
    })
    # Private audit trail includes transaction-level detail for instructor review.
    for transaction in result["transactions"]:
        append_jsonl(DATA / "audit.jsonl", {"event": "simulated_purchase", **transaction})
    # Full private run reports are not served by a public route.
    save_json(REPORTS / f"day_{day:03d}_{result['run_id']}.json", result)
    flash(
        f"Day {day} completed. Seed {seed}; {result['buyers']} buyers; "
        f"{result['units_sold']} units sold; {result['no_purchase_count']} bought nothing.",
        "success"
    )
    return redirect(url_for("index"))

@app.route("/reset", methods=["POST"])
def reset():
    if os.environ.get("MARKET_MODE", "demo").lower() == "live":
        expected = os.environ.get("ADMIN_TOKEN", "")
        if not expected or request.form.get("admin_token", "") != expected:
            abort(403, "Authorized market operator token required.")
    save_json(DATA / "state.json", {
        "day": 0, "inventory": {}, "transactions": [], "runs": [],
        "customer_profiles": {}, "customer_history": {}
    })
    append_jsonl(DATA / "audit.jsonl", {
        "event": "demo_state_reset",
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    })
    flash("Demo state reset. Audit history was preserved.", "success")
    return redirect(url_for("index"))

@app.route("/download/transactions.csv")
def download_transactions():
    state = get_state()
    rows = [public_transaction(row) for row in state.get("transactions", [])]
    output = io.StringIO(newline="")
    fields = sorted({key for row in rows for key in row.keys()}) or [
        "run_id", "day", "seller_id", "product_id", "quantity", "unit_price", "total_price"
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    memory = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    memory.seek(0)
    return send_file(memory, mimetype="text/csv", as_attachment=True, download_name="transactions.csv")

@app.route("/download/results.json")
def download_results():
    state = get_state()
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **_public_state_summary(state),
        "transactions": [public_transaction(t) for t in state.get("transactions", [])],
    }
    memory = io.BytesIO(json.dumps(payload, indent=2).encode("utf-8"))
    memory.seek(0)
    return send_file(memory, mimetype="application/json", as_attachment=True, download_name="market_results.json")

@app.route("/download/audit.jsonl")
def download_audit():
    # Keep the full audit file on the server for the instructor; public download
    # redacts seeds unless the rules explicitly allow publishing them.
    path = DATA / "audit.jsonl"
    if not path.exists():
        path.write_text("", encoding="utf-8")
    publish_seed = bool(load_config(DATA).get("publish_seed", False))
    public_lines = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("buyer_id", "buyer_type", "utility", "remaining_budget"):
                record.pop(key, None)
            if not publish_seed:
                for key in ("seed", "seed_a", "seed_b"):
                    record.pop(key, None)
            public_lines.append(json.dumps(record, sort_keys=True))
    memory = io.BytesIO(("\n".join(public_lines) + ("\n" if public_lines else "")).encode("utf-8"))
    memory.seek(0)
    return send_file(memory, mimetype="application/x-ndjson", as_attachment=True, download_name="audit.jsonl")

@app.route("/api/results")
def api_results():
    return jsonify(_public_state_summary(get_state()))

@app.route("/replay", methods=["POST"])
def replay():
    offers = get_offers()
    config = load_config(DATA)
    validation = validate_offers(offers, config)
    if validation["errors"]:
        flash("Replay stopped: fix offer-file errors first.", "error")
        return redirect(url_for("index"))
    try:
        seed = int(request.form.get("seed", "100"))
        multiplier_a = float(request.form.get("multiplier_a", "1.0"))
        multiplier_b = float(request.form.get("multiplier_b", "0.9"))
        seller_id = request.form.get("strategy_seller_id", "").strip()
        if not (0 < multiplier_a <= 10 and 0 < multiplier_b <= 10):
            raise ValueError("Price multipliers must be greater than 0 and at most 10.")
    except ValueError as exc:
        flash(f"Replay settings invalid: {exc}", "error")
        return redirect(url_for("index"))
    seller_ids = {str(o.get("seller_id", "")) for o in offers}
    if seller_id not in seller_ids:
        flash("Choose a valid seller for the strategy comparison.", "error")
        return redirect(url_for("index"))
    state = get_state()
    result = replay_runs(
        offers, config, state.get("inventory", {}), seed, seed,
        state.get("customer_profiles", {}), state.get("customer_history", {}),
        day=int(state.get("day", 0)) + 1,
        strategy_seller_id=seller_id,
        multiplier_a=multiplier_a, multiplier_b=multiplier_b
    )
    save_json(REPORTS / f"replay_{result['replay_id']}.json", result)
    append_jsonl(DATA / "audit.jsonl", {
        "event": "replay_comparison", "replay_id": result["replay_id"],
        "seed": seed, "strategy_seller_id": seller_id,
        "multiplier_a": multiplier_a, "multiplier_b": multiplier_b,
        "timestamp_utc": result["timestamp_utc"],
        "summary_a": result["summary_a"], "summary_b": result["summary_b"]
    })
    return render_template("replay.html", result=result)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "toy-soldier-buyer-market"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
