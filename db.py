import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Opens a new connection to the products database using env-configured settings."""
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "nutrition_db"),
        host=os.getenv("DB_HOST", "localhost"),
    )
