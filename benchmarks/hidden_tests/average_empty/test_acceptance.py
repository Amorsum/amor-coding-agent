import unittest

from src.calculator import average


class AverageAcceptanceTests(unittest.TestCase):
    def test_empty_collection(self) -> None:
        self.assertEqual(average([]), 0.0)

    def test_existing_behavior_is_preserved(self) -> None:
        self.assertEqual(average([-2.0, 2.0]), 0.0)


if __name__ == "__main__":
    unittest.main()

