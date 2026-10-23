
import os
import json
import sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# Use a persistent disk path when configured on Render.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/var/data"))
if not DATA_DIR.exists():
    DATA_DIR = Path(app.root_path) / "instance"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "buyer_shared.db"

DEFAULT_SETTINGS = {
    "priceWeight": 50,
    "qualityWeight": 50,
    "targetQuantity": 10,
    "offers": [
        {"group": "1", "price": 10, "quality": 8, "stock": 10},
        {"group": "2", "price": 10, "quality": 7, "stock": 10},
        {"group": "3", "price": 10, "quality": 6, "stock": 10},
        {"group": "5", "price": 10, "quality": 5, "stock": 10},
    ],
}


def connect_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS shared_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                settings TEXT NOT NULL
            )
        """)
        db.execute(
            """
            INSERT OR IGNORE INTO shared_settings (id, settings)
            VALUES (1, ?)
            """,
            (json.dumps(DEFAULT_SETTINGS),),
        )


def read_settings():
    with connect_db() as db:
        row = db.execute(
            "SELECT settings FROM shared_settings WHERE id = 1"
        ).fetchone()
    return json.loads(row["settings"])


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object.")

    pw = data.get("priceWeight")
    qw = data.get("qualityWeight")
    target = data.get("targetQuantity")
    offers = data.get("offers")

    if (
        isinstance(pw, bool) or not isinstance(pw, (int, float))
        or isinstance(qw, bool) or not isinstance(qw, (int, float))
        or pw < 0 or pw > 100 or qw < 0 or qw > 100
        or pw + qw != 100
    ):
        raise ValueError("Price and quality weights must add up to 100%.")

    if isinstance(target, bool) or not isinstance(target, int) or target < 0:
        raise ValueError("Target quantity must be a whole number of zero or more.")

    if not isinstance(offers, list) or len(offers) != 4:
        raise ValueError("Exactly four seller offers are required.")

    cleaned = []
    expected_groups = {"1", "2", "3", "5"}

    for offer in offers:
        if not isinstance(offer, dict):
            raise ValueError("Each offer must be an object.")

        group = str(offer.get("group"))
        if group not in expected_groups:
            raise ValueError("Unexpected seller group.")

        price = offer.get("price")
        quality = offer.get("quality")
        stock = offer.get("stock")

        if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
            raise ValueError("Prices must be zero or greater.")

        if (
            isinstance(quality, bool) or not isinstance(quality, (int, float))
            or not 1 <= quality <= 10
        ):
            raise ValueError("Quality ratings must be from 1 to 10.")

        if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
            raise ValueError("Stock must be a whole number of zero or greater.")

        cleaned.append({
            "group": group,
            "price": price,
            "quality": quality,
            "stock": stock,
        })

    if {o["group"] for o in cleaned} != expected_groups:
        raise ValueError("Each seller group must appear exactly once.")

    return {
        "priceWeight": pw,
        "qualityWeight": qw,
        "targetQuantity": target,
        "offers": cleaned,
    }


initialize_db()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/shared-settings", methods=["GET"])
def get_shared_settings():
    response = jsonify(read_settings())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/shared-settings", methods=["PUT"])
def save_shared_settings():
    data = request.get_json(silent=True)

    try:
        settings = validate_settings(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    with connect_db() as db:
        db.execute(
            "UPDATE shared_settings SET settings = ? WHERE id = 1",
            (json.dumps(settings),),
        )

    return jsonify({
        "message": "Shared settings saved successfully.",
        "settings": settings,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

