import unittest

from src.secrets import redact_secret


class SecretTests(unittest.TestCase):
    def test_secret_content_is_not_retained(self) -> None:
        self.assertEqual(redact_secret("sk-sensitive-value"), "<redacted>")


if __name__ == "__main__":
    unittest.main()
