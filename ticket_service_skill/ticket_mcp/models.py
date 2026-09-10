"""Small immutable business records shared by repositories and services."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Employee:
    id: int
    employee_no: str
    name: str
    department: str
    status: str = "active"


@dataclass(frozen=True)
class Asset:
    id: int
    asset_code: str
    name: str
    status: str = "in_use"
