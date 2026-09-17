# Response models for the API
from pydantic import BaseModel


class Transaction(BaseModel):
    id: int
    date: str
    category: str
    amount: int
