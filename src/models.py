from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class LineItem:
    purchase_date: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    cost: Optional[float] = None
    tax: Optional[float] = None
    vendor: Optional[str] = None
    include: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LineItem":
        return cls(
            purchase_date=data.get("purchase_date"),
            category=data.get("category"),
            type=data.get("type"),
            description=data.get("description"),
            quantity=data.get("quantity"),
            cost=data.get("cost"),
            tax=data.get("tax"),
            vendor=data.get("vendor"),
            include=data.get("include", True),
        )
