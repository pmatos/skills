from shipquote.address import Address


class UnsupportedDestination(ValueError):
    pass


# First character of the postal code -> zone.
_PREFIXES = {
    "CA": {
        "H": "CA-EAST",
        "K": "CA-EAST",
        "M": "CA-EAST",
        "T": "CA-WEST",
        "V": "CA-WEST",
    },
    "US": {str(d): "US-EAST" for d in range(0, 5)} | {str(d): "US-WEST" for d in range(5, 10)},
}

_FALLBACK = {"CA": "CA-REMOTE", "US": "US-REMOTE"}


def zone_for(address: Address) -> str:
    """Zone for an already-normalized address."""
    prefixes = _PREFIXES.get(address.country)
    if prefixes is None:
        raise UnsupportedDestination(address.country)
    return prefixes.get(address.postal_code[:1], _FALLBACK[address.country])
