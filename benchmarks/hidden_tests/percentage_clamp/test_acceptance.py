import unittest

from src.percentages import clamp_percentage


class PercentageAcceptanceTests(unittest.TestCase):
    def test_upper_bound_is_enforced(self) -> None:
        self.assertEqual(clamp_percentage(150.0), 100.0)

    def test_in_range_value_is_preserved(self) -> None:
        self.assertEqual(clamp_percentage(42.5), 42.5)


if __name__ == "__main__":
    unittest.main()
