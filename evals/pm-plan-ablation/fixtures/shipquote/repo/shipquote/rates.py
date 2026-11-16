from shipquote.zones import zone_for

# Zone -> (base cents per parcel, cents per started 500 g).
_RATES = {
    "CA-EAST": (900, 150),
    "CA-WEST": (1100, 175),
    "CA-REMOTE": (2400, 400),
    "US-EAST": (800, 120),
    "US-WEST": (850, 130),
    "US-REMOTE": (2000, 350),
}

FREE_SHIPPING_CENTS = 15000


def price_shipment(shipment) -> int:
    base, per_step = _RATES[zone_for(shipment.destination)]
    steps = -(-shipment.parcel.weight_g // 500)
    return base + per_step * steps
