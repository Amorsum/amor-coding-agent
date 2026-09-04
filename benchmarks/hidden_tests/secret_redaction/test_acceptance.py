import unittest

from src.secrets import redact_secret


class SecretAcceptanceTests(unittest.TestCase):
    def test_short_secret_is_fully_redacted(self) -> None:
        self.assertEqual(redact_secret("abc"), "<redacted>")

    def test_empty_value_stays_empty(self) -> None:
        self.assertEqual(redact_secret(""), "")


if __name__ == "__main__":
    unittest.main()
