from dataclasses import dataclass

from shipquote.address import Address


@dataclass(frozen=True)
class Item:
    sku: str
    weight_g: int
    quantity: int = 1


@dataclass(frozen=True)
class Order:
    items: tuple[Item, ...]
    destination: Address
    subtotal_cents: int
