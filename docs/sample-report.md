# Data quality report: shopflow-datagen scale 1, dirty mode

```
DATA QUALITY SCORE

████████████████░░░░ 82%

Rows analyzed                394,856
Tables / columns            5 / 38   
Checks                            30  (23 pass, 3 warn, 4 fail)
Null violations                  999
Duplicate rows                   505
Orphan references                175
Schema drift rows             20,101
Value mismatches                 160
Statistical outliers           1,109
Elapsed                        0.32s

STATUS: FAIL
```

| Status | Check | Severity | Failed | Of | Ratio | Detail | Sample |
|---|---|---|---:|---:|---:|---|---|
| PASS | `schema(customers)` | error | 0 | 20,000 | 0.0000% |  |  |
| PASS | `unique(customers.customer_id)` | error | 0 | 20,000 | 0.0000% | rows beyond the first per key |  |
| PASS | `not_null(customers.customer_id)` | error | 0 | 20,000 | 0.0000% |  |  |
| WARN | `not_null(customers.email)` | warn | 211 | 20,000 | 1.0550% |  |  |
| PASS | `accepted_values(customers.state)` | error | 0 | 20,000 | 0.0000% |  |  |
| PASS | `schema(products)` | error | 0 | 5,000 | 0.0000% |  |  |
| PASS | `unique(products.product_id)` | error | 0 | 5,000 | 0.0000% | rows beyond the first per key |  |
| PASS | `unique(products.sku)` | error | 0 | 5,000 | 0.0000% | rows beyond the first per key |  |
| PASS | `range(products.price_cents)` | error | 0 | 5,000 | 0.0000% | [1, None] |  |
| PASS | `range(products.cost_cents)` | error | 0 | 5,000 | 0.0000% | [0, None] |  |
| FAIL | `schema(orders)` | error | 20,101 | 100,505 | 20.0000% | part-00001.parquet: missing ['channel'], unexpected ['coupon_code', 'sales_channel'] | `part-00001.parquet` |
| FAIL | `unique(orders.order_id)` | error | 505 | 100,505 | 0.5025% | rows beyond the first per key | `3674`, `48399`, `45493`, `62425`, `71190` |
| WARN | `not_null(orders.channel)` | warn | 788 | 80,404 | 0.9801% |  |  |
| PASS | `foreign_key(orders.customer_id)` | error | 0 | 100,505 | 0.0000% | -> customers.customer_id |  |
| PASS | `accepted_values(orders.status)` | error | 0 | 100,505 | 0.0000% |  |  |
| PASS | `accepted_values(orders.channel)` | error | 0 | 79,616 | 0.0000% |  |  |
| PASS | `range(orders.total_cents)` | error | 0 | 100,505 | 0.0000% | [0, None] |  |
| PASS | `not_null(orders.delivered_at)` | error | 0 | 92,859 | 0.0000% | only where {'status': ['delivered', 'returned']} |  |
| PASS | `schema(order_items)` | error | 0 | 169,351 | 0.0000% |  |  |
| PASS | `unique(order_items.order_item_id)` | error | 0 | 169,351 | 0.0000% | rows beyond the first per key |  |
| PASS | `foreign_key(order_items.order_id)` | error | 0 | 169,351 | 0.0000% | -> orders.order_id |  |
| FAIL | `foreign_key(order_items.product_id)` | error | 175 | 169,351 | 0.1033% | -> products.product_id | `7240`, `12031`, `11862`, `10961`, `14236` |
| PASS | `range(order_items.quantity)` | error | 0 | 169,351 | 0.0000% | [1, 100] |  |
| FAIL | `matches_reference(order_items.unit_price_cents)` | error | 160 | 169,176 | 0.0946% | == products.price_cents by product_id | `2026`, `1309`, `943`, `656`, `4440` |
| WARN | `outlier_iqr(order_items.unit_price_cents)` | warn | 1,109 | 169,351 | 0.6549% | log10 fences [2.220, 5.492], k=3.0 | `339000`, `719000`, `7389000`, `399290`, `2239000` |
| PASS | `schema(payments)` | error | 0 | 100,000 | 0.0000% |  |  |
| PASS | `unique(payments.payment_id)` | error | 0 | 100,000 | 0.0000% | rows beyond the first per key |  |
| PASS | `foreign_key(payments.order_id)` | error | 0 | 100,000 | 0.0000% | -> orders.order_id |  |
| PASS | `accepted_values(payments.method)` | error | 0 | 100,000 | 0.0000% |  |  |
| PASS | `range(payments.installments)` | error | 0 | 100,000 | 0.0000% | [1, 12] |  |
