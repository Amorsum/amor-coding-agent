import unittest

from src.inventory import remaining_stock


class InventoryTests(unittest.TestCase):
    def test_negative_request_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            remaining_stock(10, -1)


if __name__ == "__main__":
    unittest.main()
