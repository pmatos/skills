import unittest

from shipquote.order import Item
from shipquote.parcels import pack


class PackTest(unittest.TestCase):
    def test_single_light_item(self):
        parcels = pack((Item("mug", 400),))
        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0].weight_g, 400)

    def test_splits_over_limit(self):
        parcels = pack((Item("book", 900, quantity=3),))
        self.assertEqual(sorted(p.weight_g for p in parcels), [900, 1800])

    def test_rejects_oversized_item(self):
        with self.assertRaises(ValueError):
            pack((Item("anvil", 2500),))
