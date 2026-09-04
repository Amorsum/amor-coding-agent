import unittest

from src.backoff import backoff_delay


class BackoffAcceptanceTests(unittest.TestCase):
    def test_zero_attempt_uses_base_delay(self) -> None:
        self.assertEqual(backoff_delay(0, 3), 3)

    def test_delays_double(self) -> None:
        self.assertEqual([backoff_delay(i) for i in range(4)], [1, 2, 4, 8])


if __name__ == "__main__":
    unittest.main()
