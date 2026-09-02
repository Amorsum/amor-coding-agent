import unittest

from src.config import parse_port


class ParsePortTests(unittest.TestCase):
    def test_typical_port(self) -> None:
        self.assertEqual(parse_port("8080"), 8080)

    def test_zero_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_port(0)

    def test_too_large_port_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_port(70000)


if __name__ == "__main__":
    unittest.main()

