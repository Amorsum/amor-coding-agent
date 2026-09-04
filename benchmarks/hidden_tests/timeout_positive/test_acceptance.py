import unittest

from src.timeouts import validate_timeout


class TimeoutAcceptanceTests(unittest.TestCase):
    def test_negative_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_timeout(-1)

    def test_positive_value_is_preserved(self) -> None:
        self.assertEqual(validate_timeout(30), 30)


if __name__ == "__main__":
    unittest.main()
