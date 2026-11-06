from sqlalchemy import create_engine
from dotenv import load_dotenv
import os

from data_preparation import build_star_schema

load_dotenv(override=True)
db_password = os.getenv('OLIST_DB_PASSWORD')

engine = create_engine(f'postgresql://postgres:{db_password}@localhost:5432/olist_dwh')

# build all 5 tables by calling the imported function
fact_orders, dim_customers, dim_products, dim_sellers, dim_date = build_star_schema()

# load into Postgres
fact_orders.to_sql('fact_orders', engine, if_exists='replace', index=False)
dim_customers.to_sql('dim_customers', engine, if_exists='replace', index=False)
dim_products.to_sql('dim_products', engine, if_exists='replace', index=False)
dim_sellers.to_sql('dim_sellers', engine, if_exists='replace', index=False)
dim_date.to_sql('dim_date', engine, if_exists='replace', index=False)

print("All tables loaded successfully")