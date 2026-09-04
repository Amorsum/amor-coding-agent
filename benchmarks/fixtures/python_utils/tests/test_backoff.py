import unittest

from src.backoff import backoff_delay


class BackoffTests(unittest.TestCase):
    def test_delay_is_exponential(self) -> None:
        self.assertEqual(backoff_delay(3, 2), 16)


if __name__ == "__main__":
    unittest.main()
