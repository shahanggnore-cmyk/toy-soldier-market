# Toy Soldier Buyer Market — enhanced classroom prototype

This project is an expanded Flask website for the buyer team. It includes a seller directory, configurable public rules/schedule/announcements, offer validation, seeded daily simulations, inventory carry-forward, aggregate results, CSV/JSON downloads, an append-only JSONL audit log, replay comparisons, a public JSON results endpoint, and automated tests.

**It is not a production-ready public market until you replace all sample data, confirm the rules with your instructor, and secure/deploy it.** The provided seller names and offer prices are illustrative placeholders.

## Run on Windows

1. Extract this ZIP.
2. Open the extracted `toy_soldier_buyer_market_complete` folder.
3. Click the File Explorer address bar, type `cmd`, and press Enter.
4. Run these one at a time:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

5. Open `http://127.0.0.1:5000` in Chrome.
6. Keep the black Command Prompt window open while using the site.

## Configure before class launch

- `data/sellers.json`: replace sample sellers with official team names, descriptions, and URLs.
- `data/announcements.json`: add official announcements.
- `data/rules.json`: replace cutoff, results release, timezone, customer mix, product values, and all other parameters with instructor-approved values.
- `data/offers.csv`: replace sample offers with the agreed official offer file.
- `PRICE_FILE_SPEC.md`: review the proposed CSV schema with the instructor before requiring sellers to use it.

## Main features

- `/` — market home, seller directory, schedule/rules, offers, validation, run controls, aggregate results.
- `/run` — run next simulated day; existing inventory is carried forward.
- `/replay` — compare two seeds using the same starting inventory without mutating the market state.
- `/api/results` — JSON results endpoint.
- `/health` — health check.
- Download links — transactions CSV, results JSON, audit JSONL.

## Testing

From the project folder, activate the virtual environment, then run:

```bat
python -m unittest discover -s tests -v
```

## Important limitations to resolve before submission

- The default customer types and values are examples only; the instructor must approve the behavioral model.
- The app does not automatically enforce the real-world offer cutoff or scheduled release time.
- The starter supports one product per offer row, not arbitrary bundles or every multi-product pricing structure.
- `data/state.json` is a local JSON store, not a multi-user database. It is unsuitable for concurrent production traffic.
- The reset route is not protected by authentication. Do not expose it publicly without access control.
- The local Flask server is not a public URL. Deployment to a host, environment variables, persistent storage, and a security review are required.
- Public audit/result endpoints should be reviewed for privacy and course policy before sharing.
- Validate all economic assumptions and report results transparently; do not present simulated values as real market data.

## Suggested final submission package

1. Public market URL and screenshots.
2. Approved rules and customer-model specification.
3. Price-file specification and sample CSV.
4. Code and automated test output.
5. Transaction/audit exports.
6. Model explanation, assumptions, limitations, validation results, and economic analysis.
