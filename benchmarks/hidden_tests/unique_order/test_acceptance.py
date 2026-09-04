import unittest

from src.sequences import unique_in_order


class UniqueAcceptanceTests(unittest.TestCase):
    def test_negative_and_repeated_values_preserve_order(self) -> None:
        self.assertEqual(unique_in_order([2, -1, 2, 0, -1]), [2, -1, 0])

    def test_empty_input_stays_empty(self) -> None:
        self.assertEqual(unique_in_order([]), [])


if __name__ == "__main__":
    unittest.main()
