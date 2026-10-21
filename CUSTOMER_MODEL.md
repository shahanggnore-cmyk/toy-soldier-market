# Customer model (sample configuration — instructor approval required)

The live scored parameters must be approved by the instructor before the team sees the evaluated prices. The values in `data/rules.json` are demonstration values, not official course parameters.

## Choice rule

For each customer in a seeded randomized order, the engine considers offers that are active, visible under that customer's search limit, in stock, affordable, and eligible for that customer type. It calculates:

`utility = customer value for product - total offer price + loyalty benefit - inconvenience cost`

A customer buys the offer with the highest **positive** utility. Exact ties are resolved randomly using the saved seed. If no offer has positive utility, the customer buys nothing. Each customer is processed once per day and therefore makes at most one purchase. The engine deducts purchased virtual units and spending immediately before processing the next customer.

## Demonstration customer types

- `bargain_hunter`: low product values and a $10 budget; likely to reject offers that are too expensive for the value they perceive.
- `collector`: higher values for the listed product and premium-product IDs, larger budget, and a loyalty benefit after prior purchases from that seller.
- `convenience_shopper`: moderate values, a $20 budget, and a search limit of two randomly selected sellers; has a small inconvenience cost.
- `returning_customer`: stable identity and type across days, with purchase history and a seller loyalty benefit.

The model includes a 50% returning-customer fraction. Budgets renew daily as explicitly configured; returning customers keep their type and ID, and their purchase history is retained privately. New customers are generated for the remaining daily slots. Advertising settings are inert by default; only an instructor-announced seller and consideration-probability lift should be entered. Advertising changes consideration only and does not guarantee a sale.

## Public/private data

Public downloads contain seller/product transactions and aggregate results but omit buyer IDs, individual customer types, utilities, and remaining individual budgets. The local `data/state.json` and `reports/` files contain private simulation state and should not be made publicly accessible.

## Limitations to resolve with the instructor

- Bundle offers are supported through `bundle_components` and deduct each component from the seller’s virtual inventory. Component offers must exist in the same seller’s offer file.
- Loyalty is a simple configured benefit after prior purchases from a seller. Reward funding, expiry, and exact parameters require instructor approval.
- The app records a seller's published timestamp but does not yet enforce the real-world cutoff or automatically fetch seller websites.
- The local JSON ledger is a classroom prototype, not a concurrent production database. Protect administrative actions and use persistent storage before scored play.
