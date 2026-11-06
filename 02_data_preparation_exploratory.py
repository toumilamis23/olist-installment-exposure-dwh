import pandas as pd

# load raw source data — pipeline must run standalone, no dependency on exploration script
df_orders = pd.read_csv('data/olist_orders_dataset.csv')
df_items = pd.read_csv('data/olist_order_items_dataset.csv')
df_payments = pd.read_csv('data/olist_order_payments_dataset.csv')
df_products = pd.read_csv('data/olist_products_dataset.csv')
df_sellers = pd.read_csv('data/olist_sellers_dataset.csv')
df_customers = pd.read_csv('data/olist_customers_dataset.csv')
df_reviews = pd.read_csv('data/olist_order_reviews_dataset.csv')
df_translation = pd.read_csv('data/product_category_name_translation.csv')

######################################################################################

# Fix #1: flag 8 orders where status=delivered but delivery date is missing (data gap, not deleted)
date_columns = [
    'order_purchase_timestamp',
    'order_approved_at',
    'order_delivered_carrier_date',
    'order_delivered_customer_date',
    'order_estimated_delivery_date'
]

# convert to real datetime needed for accurate date comparisons/joins later
for col in date_columns:
    df_orders[col] = pd.to_datetime(df_orders[col])

# isolate the anomalous rows for reference
anomalous_orders = df_orders[
    (df_orders['order_status'] == 'delivered') &
    (df_orders['order_delivered_customer_date'].isnull())
]
print(len(anomalous_orders))

# non-destructive flag lets delivery-time KPIs filter these out without dropping the order entirely
df_orders['is_delivery_data_valid'] = ~(
    (df_orders['order_status'] == 'delivered') &
    (df_orders['order_delivered_customer_date'].isnull())
)
print(df_orders['is_delivery_data_valid'].value_counts())

# Fix #2: aggregate payments to one row per order raw table has ~3% orders with multiple payment rows (e.g. stacked vouchers)
payments_agg = df_payments.groupby('order_id').agg(
    total_payment_value=('payment_value', 'sum'),
    max_installments=('payment_installments', 'max'),
    payment_count=('payment_sequential', 'count')  # QA helper only, dropped before final fact table
).reset_index()

print(payments_agg.shape)
print(payments_agg.head())

# sanity check confirms multi-row orders (up to 29 rows) collapsed correctly
print(payments_agg['payment_count'].value_counts().sort_index(ascending=False).head(10))

# Fix #3: correct 2 orders with installments=0 (logically invalid, min valid value is 1)
zero_check = payments_agg[payments_agg['max_installments'] == 0]
print(zero_check)
payments_agg.loc[payments_agg['max_installments'] == 0, 'max_installments'] = 1
print((payments_agg['max_installments'] == 0).sum())  # confirms fix applied

# Fix #4: dedupe reviews by review_id same review can legitimately link to 2+ orders (confirmed via investigation)
df_reviews_clean = df_reviews.drop_duplicates(subset=['review_id'], keep='first')
print(df_reviews_clean.shape)
print(df_reviews['review_id'].duplicated().sum())
print(df_reviews_clean['review_id'].duplicated().sum())

# Fix #5: products: fill missing/unmatched categories so no KPI group-by breaks on nulls

# Step 1: manually map 2 categories missing from the translation table
manual_translations = pd.DataFrame({
    'product_category_name': ['pc_gamer', 'portateis_cozinha_e_preparadores_de_alimentos'],
    'product_category_name_english': ['gaming_pc', 'kitchen_appliances']
})

df_translation_full = pd.concat([df_translation, manual_translations], ignore_index=True)
print(df_translation_full.shape)

# Step 2: left join keeps all products even with no category match, then label the gaps explicitly
df_products_clean = df_products.merge(
    df_translation_full,
    on='product_category_name',
    how='left'
)

df_products_clean['product_category_name_english'] = df_products_clean['product_category_name_english'].fillna('Unknown/Uncategorized')

print(df_products_clean.shape)
print(df_products_clean['product_category_name_english'].isnull().sum())  # should be 0

# Fix #6: trend-only view edge months (Sep-Dec 2016, Sep-Oct 2018) are data collection artifacts, would skew trend KPIs
df_orders_trend = df_orders[
    (df_orders['order_purchase_timestamp'] >= '2017-01-01') &
    (df_orders['order_purchase_timestamp'] < '2018-09-01')
]

print(df_orders.shape)
print(df_orders_trend.shape)

############################################################

# validate Option A decision: confirm multi-category orders are rare enough to justify "primary category" simplification
order_category_counts = df_items.merge(df_products_clean[['product_id','product_category_name_english']], on='product_id', how='left')
categories_per_order = order_category_counts.groupby('order_id')['product_category_name_english'].nunique()
print((categories_per_order > 1).sum())
print(len(categories_per_order))

################################################################################
# BUILDING fact_orders (grain: one row per order)
################################################################################

# primary product/seller per order = highest-value item (Option A: see log for rationale)
idx = df_items.groupby('order_id')['price'].idxmax()
primary_items = df_items.loc[idx, ['order_id', 'product_id', 'seller_id']]
primary_items = primary_items.rename(columns={
    'product_id': 'primary_product_id',
    'seller_id': 'primary_seller_id'
})

print(primary_items.shape)
print(primary_items.head())

# most frequent payment_type per order, needed for Page 2 "Payment Type Mix" KPI, dropped during first aggregation pass
payment_mode = df_payments.groupby('order_id')['payment_type'].agg(lambda x: x.mode()[0]).reset_index()
payment_mode = payment_mode.rename(columns={'payment_type': 'payment_type_mode'})

# second dedup pass, this time by order_id, review_id dedup alone left 243 orders with 2 distinct reviews, broke fact_orders grain
df_reviews_final = df_reviews_clean.drop_duplicates(subset=['order_id'], keep='first')
print(df_reviews_final['order_id'].duplicated().sum())  # confirms 0 before merging

# assemble fact table orders is the base, everything else joins on via left join to preserve all 99,441 orders
fact_orders = df_orders.merge(payments_agg, on='order_id', how='left')
fact_orders = fact_orders.drop(columns=['payment_count'])  # QA-only column, not part of final schema
fact_orders = fact_orders.merge(primary_items, on='order_id', how='left')
fact_orders = fact_orders.merge(payment_mode, on='order_id', how='left')
fact_orders = fact_orders.merge(
    df_reviews_final[['order_id', 'review_score']],
    on='order_id',
    how='left'
)

print(fact_orders.shape)
print(fact_orders['order_id'].duplicated().sum())  # must be 0; grain check
print(fact_orders.columns.tolist())

# null audit — confirms every gap is explainable, not a silent bug
print(fact_orders.isnull().sum())

# investigate: 1 "delivered" order has no payment record at all logged as known anomaly, negligible scale
missing_payment = fact_orders[fact_orders['total_payment_value'].isnull()]
print(missing_payment[['order_id', 'order_status']])

# investigate: 775 orders missing primary product/seller: confirmed explained by status (unavailable/canceled/early-stage)
missing_items = fact_orders[fact_orders['primary_product_id'].isnull()]
print(missing_items['order_status'].value_counts())

#############################################################################
# BUILDING DIMENSION TABLES
#############################################################################

# dim_customers: trimmed to fields actually used (state/city for drill-down, zip kept for granularity)
dim_customers = df_customers[['customer_id', 'customer_state', 'customer_city', 'customer_zip_code_prefix']].copy()
print(dim_customers.shape)
print(dim_customers['customer_id'].duplicated().sum())

# dim_products: only fields used by Page 2 category KPIs
dim_products = df_products_clean[['product_id', 'product_category_name_english']].copy()
print(dim_products.shape)
print(dim_products['product_id'].duplicated().sum())

# dim_sellers: same pattern as customers
dim_sellers = df_sellers[['seller_id', 'seller_state', 'seller_city', 'seller_zip_code_prefix']].copy()
print(dim_sellers.shape)
print(dim_sellers['seller_id'].duplicated().sum())

# dim_date: generated calendar table, doesn't exist in any source CSV, needed for trend KPIs (Page 4)
date_range = pd.date_range(start='2016-09-01', end='2018-10-31', freq='D')

dim_date = pd.DataFrame({'full_date': date_range})
dim_date['date_id'] = dim_date['full_date'].dt.strftime('%Y%m%d').astype(int)  # numeric key, standard DWH convention
dim_date['year'] = dim_date['full_date'].dt.year
dim_date['month'] = dim_date['full_date'].dt.month
dim_date['month_year_label'] = dim_date['full_date'].dt.strftime('%b %Y')  # readable label for Power BI axis
dim_date['month_sort_key'] = dim_date['full_date'].dt.strftime('%Y%m').astype(int)

print(dim_date.shape)
print(dim_date.head())

# add matching FK to fact_orders so it can join to dim_date
fact_orders['order_date_id'] = fact_orders['order_purchase_timestamp'].dt.strftime('%Y%m%d').astype(int)
print(fact_orders[['order_id', 'order_purchase_timestamp', 'order_date_id']].head())

# final checkpoint: confirm join integrity and all table shapes before loading to Postgres
orphans = fact_orders[~fact_orders['order_date_id'].isin(dim_date['date_id'])]
print(len(orphans))  # must be 0

print("fact_orders:", fact_orders.shape)
print("dim_customers:", dim_customers.shape)
print("dim_products:", dim_products.shape)
print("dim_sellers:", dim_sellers.shape)
print("dim_date:", dim_date.shape)