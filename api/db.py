# MySQL connection for the API
import os

import pymysql
from pymysql.cursors import DictCursor

# Credentials come from the environment. The defaults match the momo_app
# account created in section 6 of database/database_setup.sql, which holds
# SELECT/INSERT/UPDATE only - it cannot DELETE or DROP anything.
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "momo_sms_db")
DB_USER = os.getenv("DB_USER", "momo_app")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


def get_connection():
    """Open a MySQL connection that returns rows as dicts."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )
