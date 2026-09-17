# Connect to the SQLite database
import sqlite3

DB_FILE = "data/db.sqlite3"


def get_connection():
    return sqlite3.connect(DB_FILE)
