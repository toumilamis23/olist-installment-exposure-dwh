import pandas as pd


def build_star_schema():
    # load raw source data
    df_orders = pd.read_csv('data/olist_orders_dataset.csv')
    df_items = pd.read_csv('data/olist_order_items_dataset.csv')
    df_payments = pd.read_csv('data/olist_order_payments_dataset.csv')
    df_products = pd.read_csv('data/olist_products_dataset.csv')
    df_sellers = pd.read_csv('data/olist_sellers_dataset.csv')
    df_customers = pd.read_csv('data/olist_customers_dataset.csv')
    df_reviews = pd.read_csv('data/olist_order_reviews_dataset.csv')
    df_translation = pd.read_csv('data/product_category_name_translation.csv')

    ######################################################################################

    # Fix #1: flag 8 orders where status=delivered but delivery date is missing
    date_columns = [
        'order_purchase_timestamp',
        'order_approved_at',
        'order_delivered_carrier_date',
        'order_delivered_customer_date',
        'order_estimated_delivery_date'
    ]
    for col in date_columns:
        df_orders[col] = pd.to_datetime(df_orders[col])

    df_orders['is_delivery_data_valid'] = ~(
        (df_orders['order_status'] == 'delivered') &
        (df_orders['order_delivered_customer_date'].isnull())
    )

    # Fix #2: aggregate payments to one row per order
    payments_agg = df_payments.groupby('order_id').agg(
        total_payment_value=('payment_value', 'sum'),
        max_installments=('payment_installments', 'max'),
        payment_count=('payment_sequential', 'count')
    ).reset_index()

    # Fix #3: correct 2 orders with installments=0
    payments_agg.loc[payments_agg['max_installments'] == 0, 'max_installments'] = 1

    # Fix #4: dedupe reviews by review_id (same review can link to 2+ orders)
    df_reviews_clean = df_reviews.drop_duplicates(subset=['review_id'], keep='first')

    # Fix #5: products — fill missing/unmatched categories
    manual_translations = pd.DataFrame({
        'product_category_name': ['pc_gamer', 'portateis_cozinha_e_preparadores_de_alimentos'],
        'product_category_name_english': ['gaming_pc', 'kitchen_appliances']
    })
    df_translation_full = pd.concat([df_translation, manual_translations], ignore_index=True)

    df_products_clean = df_products.merge(df_translation_full, on='product_category_name', how='left')
    df_products_clean['product_category_name_english'] = df_products_clean['product_category_name_english'].fillna('Unknown/Uncategorized')

    ################################################################################
    # BUILDING fact_orders (grain: one row per order)
    ################################################################################

    # primary product/seller per order = highest-value item (Option A)
    idx = df_items.groupby('order_id')['price'].idxmax()
    primary_items = df_items.loc[idx, ['order_id', 'product_id', 'seller_id']]
    primary_items = primary_items.rename(columns={
        'product_id': 'primary_product_id',
        'seller_id': 'primary_seller_id'
    })

    # most frequent payment_type per order
    payment_mode = df_payments.groupby('order_id')['payment_type'].agg(lambda x: x.mode()[0]).reset_index()
    payment_mode = payment_mode.rename(columns={'payment_type': 'payment_type_mode'})

    # second dedup pass by order_id — review_id dedup alone left 243 orders with 2 distinct reviews
    df_reviews_final = df_reviews_clean.drop_duplicates(subset=['order_id'], keep='first')

    # assemble fact table
    fact_orders = df_orders.merge(payments_agg, on='order_id', how='left')
    fact_orders = fact_orders.drop(columns=['payment_count'])  # QA-only column
    fact_orders = fact_orders.merge(primary_items, on='order_id', how='left')
    fact_orders = fact_orders.merge(payment_mode, on='order_id', how='left')
    fact_orders = fact_orders.merge(
        df_reviews_final[['order_id', 'review_score']],
        on='order_id',
        how='left'
    )

    #############################################################################
    # BUILDING DIMENSION TABLES
    #############################################################################

    dim_customers = df_customers[['customer_id', 'customer_state', 'customer_city', 'customer_zip_code_prefix']].copy()
    dim_products = df_products_clean[['product_id', 'product_category_name_english']].copy()
    dim_sellers = df_sellers[['seller_id', 'seller_state', 'seller_city', 'seller_zip_code_prefix']].copy()

    # dim_date — generated calendar table, doesn't exist in any source CSV
    date_range = pd.date_range(start='2016-09-01', end='2018-10-31', freq='D')
    dim_date = pd.DataFrame({'full_date': date_range})
    dim_date['date_id'] = dim_date['full_date'].dt.strftime('%Y%m%d').astype(int)
    dim_date['year'] = dim_date['full_date'].dt.year
    dim_date['month'] = dim_date['full_date'].dt.month
    dim_date['month_year_label'] = dim_date['full_date'].dt.strftime('%b %Y')
    dim_date['month_sort_key'] = dim_date['full_date'].dt.strftime('%Y%m').astype(int)

    # add matching FK to fact_orders so it can join to dim_date
    fact_orders['order_date_id'] = fact_orders['order_purchase_timestamp'].dt.strftime('%Y%m%d').astype(int)

    return fact_orders, dim_customers, dim_products, dim_sellers, dim_date


if __name__ == '__main__':
    # lets this file still run standalone for testing/debugging, printing checks
    fact_orders, dim_customers, dim_products, dim_sellers, dim_date = build_star_schema()

    print("fact_orders:", fact_orders.shape)
    print("dim_customers:", dim_customers.shape)
    print("dim_products:", dim_products.shape)
    print("dim_sellers:", dim_sellers.shape)
    print("dim_date:", dim_date.shape)

    orphans = fact_orders[~fact_orders['order_date_id'].isin(dim_date['date_id'])]
    print("orphans:", len(orphans))