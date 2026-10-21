# Changes in this corrected project

- Fixed the buyer-strategy recommendation allocator so total recommended units never exceed the entered target or listed stock.
- Implemented customer-specific product values and the required utility equation.
- Added persistent returning-customer identities and seller purchase history, daily budget renewal, limited-search convenience customers, eligibility checks, and buy-nothing outcomes.
- Added stable offer IDs, ISO-8601 publication timestamps, and validation.
- Added bundle component parsing and component-stock deduction.
- Added seeded strategy replay with a common seed and starting state, changing only the selected seller's price while keeping competitor offers fixed.
- Added private transaction-level audit records; public CSV/JSON/audit downloads redact individual customer identity/type, utility, remaining personal budget, and random seeds by default.
- Added public customer-model description, offer-file specification, and customer-model documentation.
- Added automated tests for validation, budget/stock limits, reproducibility, no-purchase decisions, utility monotonicity, bundle deduction, privacy fields, and replay immutability.

## Still required before a scored round

- Replace sample prices and confirm every parameter, fallback rule, cutoff, results time, customer mix, loyalty/advertising behavior, and publication policy with the instructor.
- Add official seller website URLs when teams publish them.
- Deploy with persistent storage. Set `MARKET_MODE=live`, a strong `ADMIN_TOKEN`, and a strong `SECRET_KEY` only after the instructor approves the model and deployment.
- The app records timestamps but does not automatically enforce the cutoff/results-release schedule or fetch offers from seller websites.
- Flask route-level smoke testing should be run in the deployment environment after installing `requirements.txt`.
