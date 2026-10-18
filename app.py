from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from pathlib import Path
from datetime import datetime, timezone
import json, csv, io, os
from market import load_config, run_market_day, validate_offers, load_json, save_json, append_jsonl, aggregate_transactions, replay_runs

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-development-key-change-before-deploy")

def read_text(name, fallback=""):
    p = DATA / name
    return p.read_text(encoding="utf-8") if p.exists() else fallback

def get_state():
    return load_json(DATA / "state.json", {"day": 0, "inventory": {}, "transactions": [], "runs": []})

def get_offers():
    p = DATA / "offers.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

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
    return render_template("index.html", config=config, state=state, offers=offers,
                           validation=validation, aggregate=aggregate, sellers=sellers,
                           announcements=announcements, latest=latest)

@app.route("/run", methods=["POST"])
def run_day():
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
    result = run_market_day(offers, config, state.get("inventory", {}), day, seed)
    state["day"] = day
    state["inventory"] = result["inventory_after"]
    state.setdefault("transactions", []).extend(result["transactions"])
    state.setdefault("runs", []).append({
        "run_id": result["run_id"], "day": day, "seed": seed,
        "timestamp_utc": result["timestamp_utc"],
        "transactions": len(result["transactions"]),
        "buyers": result["buyers"], "units_sold": result["units_sold"],
        "revenue": round(result["revenue"], 2),
        "inventory_before": result["inventory_before"],
        "inventory_after": result["inventory_after"],
        "config_snapshot": config,
    })
    save_json(DATA / "state.json", state)
    append_jsonl(DATA / "audit.jsonl", {
        "event": "market_day_completed", "run_id": result["run_id"], "day": day,
        "seed": seed, "timestamp_utc": result["timestamp_utc"],
        "offer_count": len(offers), "transaction_count": len(result["transactions"]),
        "units_sold": result["units_sold"], "revenue": round(result["revenue"], 2),
        "inventory_before": result["inventory_before"],
        "inventory_after": result["inventory_after"],
    })
    save_json(REPORTS / f"day_{day:03d}_{result['run_id']}.json", result)
    flash(f"Day {day} completed. Seed {seed}; {result['buyers']} buyers; {result['units_sold']} units sold.", "success")
    return redirect(url_for("index"))

@app.route("/reset", methods=["POST"])
def reset():
    # Local classroom demo only. In a public deployment, protect administrative actions with authentication.
    save_json(DATA / "state.json", {"day": 0, "inventory": {}, "transactions": [], "runs": []})
    append_jsonl(DATA / "audit.jsonl", {"event": "demo_state_reset", "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    flash("Demo state reset. Audit history was preserved.", "success")
    return redirect(url_for("index"))

@app.route("/download/transactions.csv")
def download_transactions():
    state = get_state()
    rows = state.get("transactions", [])
    output = io.StringIO()
    fields = sorted({k for row in rows for k in row.keys()}) or ["run_id", "day", "buyer_id", "seller_id", "product_id", "quantity", "unit_price", "total_price"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="transactions.csv")

@app.route("/download/results.json")
def download_results():
    state = get_state()
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "day": state.get("day", 0),
        "aggregate": aggregate_transactions(state.get("transactions", [])),
        "runs": state.get("runs", []),
        "inventory": state.get("inventory", {}),
        "transactions": state.get("transactions", []),
    }
    mem = io.BytesIO(json.dumps(payload, indent=2).encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="application/json", as_attachment=True, download_name="market_results.json")

@app.route("/download/audit.jsonl")
def download_audit():
    p = DATA / "audit.jsonl"
    if not p.exists():
        p.write_text("", encoding="utf-8")
    return send_file(p, mimetype="application/x-ndjson", as_attachment=True, download_name="audit.jsonl")

@app.route("/api/results")
def api_results():
    state = get_state()
    return jsonify({
        "day": state.get("day", 0),
        "aggregate": aggregate_transactions(state.get("transactions", [])),
        "runs": state.get("runs", []),
        "inventory": state.get("inventory", {}),
    })

@app.route("/replay", methods=["POST"])
def replay():
    offers = get_offers()
    config = load_config(DATA)
    validation = validate_offers(offers, config)
    if validation["errors"]:
        flash("Replay stopped: fix offer-file errors first.", "error")
        return redirect(url_for("index"))
    try:
        seed_a = int(request.form.get("seed_a", "100"))
        seed_b = int(request.form.get("seed_b", "200"))
    except ValueError:
        flash("Replay seeds must be whole numbers.", "error")
        return redirect(url_for("index"))
    state = get_state()
    inventory = state.get("inventory", {})
    result = replay_runs(offers, config, inventory, seed_a, seed_b)
    save_json(REPORTS / f"replay_{result['replay_id']}.json", result)
    append_jsonl(DATA / "audit.jsonl", {
        "event": "replay_comparison", "replay_id": result["replay_id"],
        "seed_a": seed_a, "seed_b": seed_b, "timestamp_utc": result["timestamp_utc"],
        "summary_a": result["summary_a"], "summary_b": result["summary_b"]
    })
    flash(f"Replay comparison complete: seed {seed_a} vs seed {seed_b}.", "success")
    return render_template("replay.html", result=result)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "toy-soldier-buyer-market"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
