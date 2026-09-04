import unittest

from src.percentages import clamp_percentage


class PercentageTests(unittest.TestCase):
    def test_negative_percentage_clamps_to_zero(self) -> None:
        self.assertEqual(clamp_percentage(-5.0), 0.0)


if __name__ == "__main__":
    unittest.main()
