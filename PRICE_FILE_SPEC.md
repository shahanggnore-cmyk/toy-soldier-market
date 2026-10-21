# Seller price-file specification (draft for instructor approval)

CSV files must be UTF-8. This application reads `data/offers.csv`. Agree this schema with the instructor before sellers use it.

| Column | Required | Meaning |
|---|---|---|
| `offer_id` | Yes | Stable, unique ID for an offer. Keep it unchanged across updates so changing a website or quantity cannot reset virtual stock. |
| `seller_id` | Yes | Stable seller/team identifier, e.g. `G1`. |
| `seller_name` | Yes | Public seller/team name. |
| `product_id` | Yes | Stable product identifier, e.g. `TS01`. |
| `product_name` | Yes | Human-readable product name. |
| `unit_price` | Yes | Total price for one unit of this offer, in the market's agreed currency. This version supports single-product offers, not multi-item bundles. |
| `quantity` | Yes | Initial number of virtual units offered. Once initialized, the market ledger controls remaining virtual stock. |
| `effective_day` | Yes | First simulated day this offer is active; integer >= 1. |
| `eligible_customer_types` | No | Semicolon-separated allowed customer types. Blank means all types are eligible. |
| `bundle_components` | No | Optional semicolon-separated `PRODUCT_ID:COUNT` components, e.g. `TS01:2;TS02:1`. A bundle offer must have matching component inventory rows for the same seller. `unit_price` is the complete price per bundle. |
| `published_at` | Yes | ISO-8601 timestamp including timezone, e.g. `2026-10-20T22:00:00-04:00`. |

## Example

```csv
offer_id,seller_id,seller_name,product_id,product_name,unit_price,quantity,effective_day,eligible_customer_types,published_at
G1-TS01-D1,G1,Group 1,TS01,Toy Soldier,10.00,10,1,,2026-10-20T22:00:00-04:00
```

## Inventory and pricing rules

- The ledger is authoritative for remaining virtual stock. Editing `quantity` or a seller website does not replenish an offer after its stable `offer_id` has been initialized.
- Bundle rows are supported using `bundle_components`. Buying a bundle deducts the bundle quantity and every required component unit from the seller’s virtual component stock. Every component must have an inventory row for the same seller.
- `unit_price` is the complete price charged for one listed unit or complete bundle. Discounts already included in this price must not also be counted as a separate loyalty benefit.
- Invalid/missing submissions need an instructor-approved fallback policy. This prototype reports validation errors; it does not silently invent a replacement offer.
- Physical stock and physical sales are outside this system and must never be deducted or combined with virtual purchases.
