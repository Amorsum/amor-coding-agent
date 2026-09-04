import unittest

from src.timeouts import validate_timeout


class TimeoutTests(unittest.TestCase):
    def test_zero_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_timeout(0)


if __name__ == "__main__":
    unittest.main()
