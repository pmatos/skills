from dataclasses import dataclass

from shipquote.order import Order
from shipquote.parcels import Shipment, consolidate, pack
from shipquote.rates import FREE_SHIPPING_CENTS, price_shipment


@dataclass(frozen=True)
class Quote:
    parcel_count: int
    shipping_cents: int


def quote(order: Order) -> Quote:
    destination = order.destination.normalized()
    parcels = pack(order.items)
    if order.subtotal_cents >= FREE_SHIPPING_CENTS:
        return Quote(len(parcels), 0)
    if len(parcels) == 1:
        return Quote(1, price_shipment(Shipment(parcels[0], destination)))
    shipments = consolidate(parcels, order)
    return Quote(len(shipments), sum(price_shipment(s) for s in shipments))
