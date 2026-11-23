"""Schémas de validation des corps de requête (Pydantic v2)."""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

HEX = r"^#[0-9a-fA-F]{6}$"


class LoginIn(BaseModel):
    username: str = Field(default="", max_length=80)
    password: str = Field(default="", max_length=256)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    is_admin: bool = False


class UserPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class TransactionIn(BaseModel):
    date: dt.date
    type: Literal["Entrée", "Sortie", "Transfert"]
    account: str = Field(min_length=1, max_length=120)
    target_account: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    name: str = Field(default="", max_length=200)
    amount: float = Field(ge=0.01, le=1_000_000_000)


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InitialBalanceIn(BaseModel):
    initial_balance: float = Field(ge=-1_000_000_000, le=1_000_000_000)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(pattern=HEX)


class CategoryColorIn(BaseModel):
    color: str = Field(pattern=HEX)


class PasswordIn(BaseModel):
    enabled: bool
    password: str | None = Field(default=None, max_length=256)
