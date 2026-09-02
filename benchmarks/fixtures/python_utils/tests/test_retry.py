import unittest

from src.retry import retry_delays


class RetryDelayTests(unittest.TestCase):
    def test_default_retry_count(self) -> None:
        self.assertEqual(retry_delays(), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()

