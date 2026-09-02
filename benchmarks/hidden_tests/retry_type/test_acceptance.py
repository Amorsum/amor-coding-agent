import unittest

from src.retry import DEFAULT_RETRIES, retry_delays


class RetryTypeAcceptanceTests(unittest.TestCase):
    def test_default_configuration_is_an_integer(self) -> None:
        self.assertIsInstance(DEFAULT_RETRIES, int)
        self.assertEqual(DEFAULT_RETRIES, 3)

    def test_explicit_retry_count_is_preserved(self) -> None:
        self.assertEqual(retry_delays(2), [0, 1])


if __name__ == "__main__":
    unittest.main()

