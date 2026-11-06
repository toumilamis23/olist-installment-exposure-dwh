import pandas as pd 
######################################################################

#table_orders
df_orders= pd.read_csv('data/olist_orders_dataset.csv')

#structure
pd.set_option('display.max_columns', None)
print(df_orders.shape)
print(df_orders.head())

# completneness
print(df_orders.isnull().sum())
print(df_orders['order_delivered_customer_date'].isnull().groupby(df_orders['order_status']).sum())

non_delivered_statuses = ['created', 'approved', 'invoiced', 'processing', 'shipped']
contradictions= df_orders [(df_orders['order_status'].isin(non_delivered_statuses))& (df_orders['order_delivered_customer_date'].notnull())]
print(len(contradictions))

#uniqueness
print(df_orders['order_id'].duplicated().sum())

#validity
# we kinda already checked the validity of teh data above as we have no typos or inconsistent spelling
# Convert date columns to datetime before performing date comparisons or calculations
date_columns = [
    'order_purchase_timestamp',
    'order_approved_at',
    'order_delivered_carrier_date',
    'order_delivered_customer_date',
    'order_estimated_delivery_date'
]
for col in date_columns:
    df_orders[col] = pd.to_datetime(df_orders[col])

#check if we have any weird dates 
weird_dates= df_orders[(df_orders['order_delivered_customer_date'])<(df_orders['order_purchase_timestamp'])]
print(len(weird_dates))
print(df_orders.dtypes)
##############################################################################################

#table_order-items
df_items = pd.read_csv('data/olist_order_items_dataset.csv')
print(df_items.shape)
print(df_items.head())
print(df_items.isnull().sum())
print(df_items.duplicated(subset=['order_id', 'order_item_id']).sum())
print(df_items['price'].describe())
print(df_items['freight_value'].describe())
orphans = df_items[~df_items['order_id'].isin(df_orders['order_id'])]
print(len(orphans))
##############################################################################################

#table_payments
df_payments = pd.read_csv('data/olist_order_payments_dataset.csv')
print(df_payments.shape)
print(df_payments.head())
print(df_payments.isnull().sum())
print(df_payments.duplicated(subset=['order_id', 'payment_sequential']).sum())
print(df_payments['payment_value'].describe())
print(df_payments['payment_installments'].describe())

#installments should only exist for credit cards to confirm that:
non_credit = df_payments[(df_payments['payment_type'] != 'credit_card') & (df_payments['payment_installments'] > 1)]
print(len(non_credit))

# in inst min=0 is suspicious. An order can't logically be split into "0 installments" even a single upfront payment should be 1
zero_installments = df_payments[df_payments['payment_installments'] == 0]
print(len(zero_installments))
print(zero_installments['payment_type'].value_counts())

orphans = df_payments[~df_payments['order_id'].isin(df_orders['order_id'])]
print(len(orphans))
#############################################################################################

#table_products
df_products = pd.read_csv('data/olist_products_dataset.csv')
print(df_products.shape)
print(df_products.head())
print(df_products.isnull().sum())
same_rows = df_products[df_products['product_category_name'].isnull() & df_products['product_name_lenght'].isnull()]
print(len(same_rows))
missing_dims = df_products[df_products['product_weight_g'].isnull()]
print(missing_dims)
print(df_products['product_id'].duplicated().sum())
# check the category names
df_translation = pd.read_csv('data/product_category_name_translation.csv')
print(df_translation.head())
print(df_translation.shape)
#
unmatched = df_products[~df_products['product_category_name'].isin(df_translation['product_category_name']) & df_products['product_category_name'].notnull()]
print(len(unmatched))
print(unmatched['product_category_name'].unique())

orphans = df_items[~df_items['product_id'].isin(df_products['product_id'])]
print(len(orphans))
##############################################################################################

#table_sellers
df_sellers = pd.read_csv('data/olist_sellers_dataset.csv')
print(df_sellers.shape)
print(df_sellers.head())
print(df_sellers.isnull().sum())
print(df_sellers['seller_id'].duplicated().sum())
print(df_sellers['seller_state'].unique())
orphans = df_items[~df_items['seller_id'].isin(df_sellers['seller_id'])]
print(len(orphans))
###############################################################################################

#table_customers
df_customers = pd.read_csv('data/olist_customers_dataset.csv')
print(df_customers.shape)
print(df_customers.head())
print(df_customers.isnull().sum())
print(df_customers['customer_id'].duplicated().sum())
print(df_customers['customer_unique_id'].duplicated().sum())
print(df_customers['customer_state'].unique())
orphans = df_orders[~df_orders['customer_id'].isin(df_customers['customer_id'])]
print(len(orphans))

##############################################################################################

#table_order-reviews
df_reviews = pd.read_csv('data/olist_order_reviews_dataset.csv')
print(df_reviews.shape)
print(df_reviews.head())
print(df_reviews.isnull().sum())
print(df_reviews['review_id'].duplicated().sum())
print(df_reviews['order_id'].duplicated().sum())
dup_ids = df_reviews[df_reviews['review_id'].duplicated(keep=False)]
print(dup_ids.sort_values('review_id').head(10))
check = df_reviews[df_reviews.duplicated(subset=['review_id','review_score','review_comment_message','review_answer_timestamp'], keep=False)]
print(len(check))
print(df_reviews['review_score'].unique())
print(df_reviews['review_score'].describe())
orphans = df_reviews[~df_reviews['order_id'].isin(df_orders['order_id'])]
print(len(orphans))
###############################################################################################

#table_geolocation
df_geo = pd.read_csv('data/olist_geolocation_dataset.csv')
print(df_geo.shape)
print(df_geo.head())
print(df_geo.isnull().sum())
print(df_geo['geolocation_zip_code_prefix'].duplicated().sum())
print(df_geo['geolocation_zip_code_prefix'].nunique())
print(df_geo['geolocation_lat'].describe())
print(df_geo['geolocation_lng'].describe())
bad_coords = df_geo[
    (df_geo['geolocation_lat'] > 5) | (df_geo['geolocation_lat'] < -34) |
    (df_geo['geolocation_lng'] > -34) | (df_geo['geolocation_lng'] < -74)
]
print(len(bad_coords))