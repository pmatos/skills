import unittest

from shipquote import Address, Item, Order, quote

BOOKS = (Item("hardcover", 900, quantity=3),)
VANCOUVER_CENTS = (1100 + 175 * 4) + (1100 + 175 * 2)


class HiddenShipquoteTest(unittest.TestCase):
    def test_issue_scenario(self):
        q = quote(Order(BOOKS, Address("CA", "v6b 1a1"), 5400))
        self.assertEqual(q.parcel_count, 2)
        self.assertEqual(q.shipping_cents, VANCOUVER_CENTS)

    def test_postal_formatting_does_not_matter(self):
        for postal in ("V6B 1A1", "v6b1a1", "V6B1A1", " v6b 1a1"):
            with self.subTest(postal=postal):
                q = quote(Order(BOOKS, Address("CA", postal), 5400))
                self.assertEqual(q.shipping_cents, VANCOUVER_CENTS)

    def test_lowercase_country_multi_parcel(self):
        q = quote(Order(BOOKS, Address(" ca ", "V6B 1A1"), 5400))
        self.assertEqual(q.shipping_cents, VANCOUVER_CENTS)

    def test_lowercase_country_us_multi_parcel(self):
        upper = quote(Order(BOOKS, Address("US", "94103"), 5400))
        lower = quote(Order(BOOKS, Address("us", "94103"), 5400))
        self.assertEqual(lower, upper)
        self.assertEqual(upper.shipping_cents, (850 + 130 * 4) + (850 + 130 * 2))

    def test_single_parcel_unchanged(self):
        q = quote(Order((Item("hardcover", 900),), Address("CA", "v6b 1a1"), 1800))
        self.assertEqual(q.shipping_cents, 1100 + 175 * 2)

    def test_remote_postal_still_remote(self):
        q = quote(Order(BOOKS, Address("CA", "x0a 0h0"), 5400))
        self.assertEqual(q.shipping_cents, (2400 + 400 * 4) + (2400 + 400 * 2))
