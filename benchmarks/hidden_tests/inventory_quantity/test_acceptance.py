import unittest

from src.inventory import remaining_stock


class InventoryAcceptanceTests(unittest.TestCase):
    def test_excess_request_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            remaining_stock(2, 3)

    def test_valid_request_returns_remainder(self) -> None:
        self.assertEqual(remaining_stock(5, 2), 3)


if __name__ == "__main__":
    unittest.main()
