import unittest

from src.orders import order_total


class OrderDiscountAcceptanceTests(unittest.TestCase):
    def test_no_discount_preserves_subtotal(self) -> None:
        self.assertEqual(order_total([10.0, 15.0]), 25.0)

    def test_full_discount_returns_zero(self) -> None:
        self.assertEqual(order_total([10.0, 15.0], 1.0), 0.0)

    def test_invalid_discount_uses_pricing_validation(self) -> None:
        with self.assertRaises(ValueError):
            order_total([10.0], 1.5)


if __name__ == "__main__":
    unittest.main()

