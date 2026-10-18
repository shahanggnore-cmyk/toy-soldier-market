# Seller price-file specification

Upload files are CSV UTF-8. The current prototype reads `data/offers.csv` and validates the following columns:

| Column | Required | Meaning | Example |
|---|---|---|---|
| `seller_id` | Yes | Stable seller/team identifier | `SELLER_A` |
| `seller_name` | Yes | Public seller name | `Sample Seller A` |
| `product_id` | Yes | Stable product identifier | `SOLDIER_RED` |
| `product_name` | Yes | Human-readable product name | `Red Toy Soldier` |
| `unit_price` | Yes | Nonnegative numeric price per unit | `12.00` |
| `quantity` | Yes | Whole number of available units | `20` |
| `effective_day` | Yes | First simulated day this offer is active (integer >= 1) | `1` |

## Example

```csv
seller_id,seller_name,product_id,product_name,unit_price,quantity,effective_day
SELLER_A,Sample Seller A,SOLDIER_RED,Red Toy Soldier,12.00,20,1
```

Before launch, confirm the required schema with the instructor. This starter does not yet support every possible bundle/multi-product pricing scheme; it treats each row as one offer for one product.
