# Save transactions to MySQL.
#
# The schema itself is created by database/database_setup.sql, not here - it is
# version-controlled SQL rather than something the ETL invents at runtime. This
# module only inserts, and relies on the database to reject bad rows: the
# UNIQUE on sms_hash makes a re-run idempotent rather than duplicating records.
#
# Connection handling lives in api/db.py (pymysql); a connection is passed in.


def insert_transactions(conn, transactions):
    # TODO
    pass


def insert_participants(conn, transaction_id, parties):
    # TODO
    pass
