import unittest

from src.orders import order_total


class OrderTotalTests(unittest.TestCase):
    def test_applies_discount(self) -> None:
        self.assertEqual(order_total([40.0, 60.0], 0.25), 75.0)


if __name__ == "__main__":
    unittest.main()

