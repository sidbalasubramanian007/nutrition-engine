import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Opens a new connection to the products database.

    Uses DATABASE_URL if set (e.g. hosted Postgres); otherwise builds the connection
    from DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD, with local defaults.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "nutrition_db"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
    )
