# Olist DWH — Data Quality Log

Running log of findings from Data Understanding phase (CRISP-DM). Updated after each table is checked. This becomes the basis for the ETL script's cleaning logic and the project README's "Design Decisions" section.

---

## Project Summary (for context if picked up cold)

**Main business question:** How much cash is Olist's marketplace fronting at any given time due to installment purchases, and where is that exposure concentrated?

**Sub-questions & dashboard pages:**
1. **Overview** — How big is the exposure overall?
2. **Concentration** — Where is it concentrated (category, region, sellers)?
3. **Risk Signal** — Is it correlated with anything risky (cancellations, late delivery, reviews)?
4. **Cost & Trend** — What does it cost, and where is it heading?

**16 KPIs (4 per page):**
- Page 1: Total Outstanding Installment Value, % of Orders Financed, Avg Installments per Financed Order, Total Revenue vs Financed Revenue
- Page 2: Exposure by Category, Exposure by Region/State, Top 10% Sellers' Share of Financed Revenue, Payment Type Mix per Category
- Page 3: Avg Installments vs Order Value, Cancellation Rate (High vs Low Installments), Late Delivery Rate on High-Installment Orders, Review Score by Installment Bucket
- Page 4: Estimated Cost of Financing, Exposure Trend/Trajectory, Projected Next-Month Exposure, Exposure as % of Total Payment Volume Over Time

**Full detail on business question/KPI rationale:** see `Olist_DWH_Project_Scoping.pdf` (companion document, generated earlier in the project).

**Star schema:** 1 fact table (`fact_orders`, grain = one row per order) + 4 dimensions (`dim_customers`, `dim_products`, `dim_sellers`, `dim_date`) — see `olist_star_schema.jpg`.

---

## Table: `orders`
- **Rows:** 99,441 | **Key:** `order_id` (confirmed unique, 0 duplicates)
- **Nulls:** `order_approved_at` (160), `order_delivered_carrier_date` (1,783), `order_delivered_customer_date` (2,965) — all explained by order_status (not-yet-delivered orders logically have no delivery date)
- **Issue found:** 8 orders with status = "delivered" are missing `order_delivered_customer_date` — logical inconsistency, likely a logging gap
  - **Decision:** Exclude these 8 rows from any delivery-time-based KPI calculations
- **Consistency check:** 0 orders with "not yet delivered" status have a delivery date filled in — passed, no contradiction
- **Date columns:** Converted all 5 to proper datetime type (were stored as text/object)

## Table: `order_items`
- **Rows:** 112,650 | **Key:** `order_id` + `order_item_id` (confirmed unique, 0 duplicates)
- **Nulls:** None — fully clean across all 7 columns
- **Validity:** `price` (min 0.85, max 6,735) and `freight_value` (min 0.00, max 409.68) — no negative values, no errors. Price is right-skewed (mean 120.65 vs median 74.99) — median is more representative for "typical" values
- **Relationships:** 0 orphan order_ids (every item correctly links to a real order in `orders`)
- **Issues found:** None

## Table: `payments`
- **Rows:** 103,886 | **Key:** `order_id` + `payment_sequential` (confirmed unique, 0 duplicates)
- **Nulls:** None — fully clean across all 5 columns
- **Validity:** `payment_value` min = 0.00 (likely voucher-stacking rows, see below); `payment_installments` min = 0 (2 rows, both credit_card — logically invalid, a payment should have at least 1 installment)
  - **Decision:** Exclude or correct these 2 rows to installments = 1 during ETL
- **Confirmed rule:** Installments > 1 only ever occur on `payment_type = credit_card` (0 exceptions found) — safe to rely on this filter
- **Structural finding:** ~3% of orders (2,382+) have multiple payment rows (e.g., one order had 29 stacked voucher rows, several with $0.00 value)
  - **Decision:** Always aggregate `SUM(payment_value) GROUP BY order_id` — never treat a single payment row as the full order value
- **Relationships:** 0 orphan order_ids (every payment correctly links to a real order in `orders`)

## Table: `products`
- **Rows:** 32,951 | **Key:** `product_id` (confirmed unique, 0 duplicates)
- **Nulls:** 610 rows missing `product_category_name`, `product_name_lenght`, `product_description_lenght`, `product_photos_qty` together — confirmed same 610 rows, single root cause (incomplete seller listings), not 4 separate issues
  - **Decision:** Label these as "Unknown/Uncategorized" in category-based KPIs rather than dropping them
- **Secondary null finding:** 2 rows missing weight/dimensions — 1 overlaps with the 610 incomplete-listing group, 1 is an isolated gap (product_id 09ff539a621711667c43eba6a3bd8466, has category but no physical specs)
  - **Decision:** Not used in this project's KPIs (weight/dimensions aren't part of the installment/payment scope) — no action needed
- **Validity:** 13 products have a `product_category_name` with no match in `product_category_name_translation.csv` — 2 distinct category names affected (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`)
  - **Decision:** Manually add these 2 categories to a local copy of the translation table (clear, identifiable meanings) rather than bucketing as "Unknown"
- **Relationships:** 0 orphan product_ids (every order_item correctly links to a real product in `products`)
- **Issues found:** Handled above — no blockers, all resolved with clear decisions

## Table: `sellers`
- **Rows:** 3,095 | **Key:** `seller_id` (confirmed unique, 0 duplicates)
- **Nulls:** None — fully clean across all 4 columns
- **Validity:** 23 distinct `seller_state` values, all valid 2-letter Brazilian state codes, consistent casing, no typos
- **Relationships:** 0 orphan seller_ids (every order_item correctly links to a real seller)
- **Issues found:** None — fully clean table

## Table: `customers`
- **Rows:** 99,441 | **Key:** `customer_id` (confirmed unique, 0 duplicates) — matches order count exactly, 1 customer_id per order
- **Nulls:** None — fully clean across all 5 columns
- **Important structural finding:** Two different customer identifiers exist — `customer_id` (unique per order) vs `customer_unique_id` (unique per real person). `customer_unique_id` has 3,345 duplicate occurrences, meaning ~3.4% of orders (3,345 of 99,441) came from a repeat customer; the other 96.6% were one-time buyers.
  - **Decision:** Not used directly in current 16 KPIs, but any future "repeat customer" or "customer lifetime" metric MUST use `customer_unique_id`, never `customer_id`, or it will incorrectly treat every customer as one-time
- **Validity:** 27 distinct `customer_state` values, all valid Brazilian state codes, consistent formatting
- **Relationships:** 0 orphan customer_ids (every order correctly links to a real customer)
- **Issues found:** None — clean table, just an important identifier distinction to remember

## Table: `order_reviews`
- **Rows:** 99,224 | **Key:** `review_id` (⚠️ NOT reliably unique — see below)
- **Nulls:** `review_comment_title` (87,656, 88%) and `review_comment_message` (58,247, 59%) — expected, most customers rate without writing text. `review_score` itself has 0 nulls.
- **Issue found — important:** 814 duplicate `review_id` values (1,603 rows total involved). Investigated a sample: duplicates share identical score, comment, and timestamps, but different `order_id`. Confirmed via broader check (1,603 rows match on review_id + score + comment + timestamp) that this is a consistent pattern, not random corruption — Olist appears to link one review to multiple orders when a customer's purchases were made close together.
  - **Decision:** Deduplicate by `review_id` before joining reviews to orders for any KPI, to avoid double-counting the same review's score across multiple orders (relevant to Page 3 "Review Score by Installment Bucket")
- **Validity:** `review_score` range is clean, exactly 1–5, no invalid values. Mean 4.09, median 5 — skews positive, typical for e-commerce reviews.
- **Relationships:** 0 orphan order_ids (every review correctly links to a real order)

## Table: `geolocation`
- **Rows:** 1,000,163 | **Structure:** many-to-one lookup — only 19,015 distinct zip code prefixes, ~52 GPS points per zip on average
- **Nulls:** None — fully clean across all 5 columns
- **Issue found:** 42 rows (0.004%) have geographically impossible coordinates for Brazil (lat/lng far outside Brazil's real range) — isolated GPS logging errors
  - **Decision:** Exclude these 42 rows if this table is ever used; negligible scale, doesn't affect overall data quality
- **Important structural finding:** This table must NOT be joined row-by-row to `customers`/`sellers` on zip code — doing so would multiply every row ~52x and break any KPI counts. Would need aggregation (e.g., average lat/lng per zip) first.
  - **Decision:** Not used in current 16 KPIs (no mapping/geo-visual planned) — table reviewed and understood, but not joined into the pipeline for this phase of the project

---

## ✅ DATA UNDERSTANDING PHASE — COMPLETE
All 9 source tables reviewed: `orders`, `order_items`, `payments`, `products`, `sellers`, `customers`, `order_reviews`, `geolocation`, and `product_category_name_translation` (reviewed via the category-match check under `products`).

Next phase: **Data Preparation** — build the ETL script that applies every decision logged above, then load into PostgreSQL.

---

## fact_orders — Final Assembly (Data Preparation)
Built by joining: `orders` (base) + `payments_agg` (aggregated) + `primary_items` (highest-value item per order) + `payment_mode` (most frequent payment type) + `df_reviews_final` (deduplicated by order_id).

**Bug caught and fixed during assembly:** initial review merge used `df_reviews_clean` (deduplicated by `review_id` only), which caused 243 duplicate rows in the final table (99,684 instead of 99,441) — some orders had 2 distinct review_ids. Fixed by additionally deduplicating reviews by `order_id` (`df_reviews_final`), restoring the correct one-row-per-order grain. Confirmed 0 duplicates after fix.

**Final shape:** 99,441 rows, 15 columns — matches finalized schema exactly.

**Null findings after assembly:**
- `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date` — expected, explained by order_status (established in Data Understanding)
- `review_score` (1,274 nulls) — expected, not every order is reviewed
- **`total_payment_value`/`max_installments`/`payment_type_mode` (1 null each)** — investigated: 1 "delivered" order has zero payment records, a genuine logical inconsistency (similar to the 8 anomalous delivery-date orders found earlier). Negligible scale (1 row), documented but not corrected — flagged as a known data gap.
- **`primary_product_id`/`primary_seller_id` (775 nulls)** — investigated: fully explained by order_status. 603 "unavailable" + 164 "canceled" + 8 early-stage orders never had confirmed items, so no primary product/seller could be assigned. Expected behavior, not a bug — these rows will naturally be excluded from category/seller-based KPIs (Page 2).

---

## ✅ STAR SCHEMA — FULLY BUILT IN PYTHON
All 5 final tables constructed and verified:
- `fact_orders`: 99,441 rows, 16 columns (includes engineered `order_date_id` key)
- `dim_customers`: 99,441 rows, 4 columns
- `dim_products`: 32,951 rows, 2 columns
- `dim_sellers`: 3,095 rows, 4 columns
- `dim_date`: 791 rows, 5 columns (generated calendar, Sept 2016 – Oct 2018)

All primary keys confirmed unique. Orphan check on `fact_orders.order_date_id` → `dim_date.date_id` passed (0 orphans). Ready for PostgreSQL load.

---

## Next phase: Load into PostgreSQL
Before loading into Postgres, every field in `fact_orders` was checked against all 16 KPIs to confirm the schema actually supports them. Two gaps were found and fixed:
- **`payment_type_mode`** added — needed for "Payment Type Mix per Category" (Page 2), which was missed when payments were first aggregated (only sum/max/count were kept, payment_type itself was dropped)
- **`order_delivered_customer_date`** and **`order_estimated_delivery_date`** added — needed for "Late Delivery Rate on High-Installment Orders" (Page 3), which requires the actual dates, not just the `is_delivery_data_valid` flag
- **Region decision:** "Exposure by Region" (Page 2) uses `customer_state`, not seller_state — exposure/financing risk is about where the financed customer is located, not where the seller operates. Seller region is still used separately for "Top 10% Sellers' Share."

**Attribute trimming decision:** every field in the final schema was checked against the 16 KPIs. `payment_count` (a Data Preparation QA helper, not a KPI input) was removed from `fact_orders`. Customer/seller `city` and `zip_code_prefix` fields were kept despite not being used by a specific KPI, as they support standard geographic drill-down in Power BI (state → city) — a deliberate exception to the "only what's used" rule, not speculative bloat.

Final `fact_orders` fields: order_id (PK), customer_id (FK), order_date_id (FK), primary_product_id (FK), primary_seller_id (FK), total_payment_value, max_installments, payment_type_mode, order_status, order_delivered_customer_date, order_estimated_delivery_date, is_delivery_data_valid, review_score

---

## Cross-cutting decisions for ETL (Data Preparation phase)
1. Filter trend/time-based KPIs to **Jan 2017 – Aug 2018** (edge months have near-zero order volume — data collection artifacts)
2. Aggregate payments by `order_id` before joining to avoid double-counting from multi-row orders
3. Exclude the 8 anomalous "delivered but no date" orders from delivery-time metrics
4. Correct or exclude the 2 zero-installment payment rows
5. Label products with missing/unmatched category as "Unknown/Uncategorized", except manually map `pc_gamer` and `portateis_cozinha_e_preparadores_de_alimentos` to English
6. Document the "cancellation = risk proxy, not confirmed loss" and "assumed cost-of-financing rate" assumptions explicitly in README