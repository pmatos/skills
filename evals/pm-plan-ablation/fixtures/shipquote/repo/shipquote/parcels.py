from dataclasses import dataclass

from shipquote.address import Address
from shipquote.order import Item, Order

MAX_PARCEL_G = 2000


@dataclass(frozen=True)
class Parcel:
    skus: tuple[str, ...]
    weight_g: int


@dataclass(frozen=True)
class Shipment:
    parcel: Parcel
    destination: Address


def pack(items: tuple[Item, ...]) -> list[Parcel]:
    """First-fit-decreasing packing into parcels of at most MAX_PARCEL_G."""
    units = sorted(
        ((item.sku, item.weight_g) for item in items for _ in range(item.quantity)),
        key=lambda unit: unit[1],
        reverse=True,
    )
    bins: list[tuple[list[str], int]] = []
    for sku, weight in units:
        if weight > MAX_PARCEL_G:
            raise ValueError(f"{sku} exceeds the {MAX_PARCEL_G} g parcel limit")
        for i, (skus, total) in enumerate(bins):
            if total + weight <= MAX_PARCEL_G:
                skus.append(sku)
                bins[i] = (skus, total + weight)
                break
        else:
            bins.append(([sku], weight))
    return [Parcel(tuple(skus), total) for skus, total in bins]


def consolidate(parcels: list[Parcel], order: Order) -> list[Shipment]:
    """Group parcels into shipments for the carrier manifest."""
    return [Shipment(parcel, order.destination) for parcel in parcels]
