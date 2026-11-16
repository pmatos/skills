import unittest

from shipquote import Address, Item, Order, quote
from shipquote.zones import UnsupportedDestination


def order(items, country="CA", postal="M5V 2T6", subtotal=5000):
    return Order(tuple(items), Address(country, postal), subtotal)


class QuoteTest(unittest.TestCase):
    def test_single_parcel_toronto(self):
        q = quote(order([Item("mug", 400)]))
        self.assertEqual(q, type(q)(1, 900 + 150))

    def test_single_parcel_lowercase_postal(self):
        self.assertEqual(
            quote(order([Item("mug", 400)], postal="m5v 2t6")),
            quote(order([Item("mug", 400)], postal="M5V 2T6")),
        )

    def test_multi_parcel_vancouver(self):
        q = quote(order([Item("book", 900, quantity=3)], postal="V6B 1A1"))
        self.assertEqual(q.parcel_count, 2)
        self.assertEqual(q.shipping_cents, (1100 + 175 * 2) + (1100 + 175 * 4))

    def test_free_shipping(self):
        q = quote(order([Item("book", 900, quantity=3)], subtotal=20000))
        self.assertEqual(q.shipping_cents, 0)

    def test_unsupported_country(self):
        with self.assertRaises(UnsupportedDestination):
            quote(order([Item("mug", 400)], country="FR", postal="75001"))
