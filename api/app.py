# Simple API (bonus)
# run with: uvicorn api.app:app --reload
from fastapi import FastAPI

app = FastAPI()


@app.get("/transactions")
def get_transactions():
    # TODO: get transactions from the database
    return []


@app.get("/analytics")
def get_analytics():
    # TODO: return totals by category
    return {}
