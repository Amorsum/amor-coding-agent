import unittest

from src.config import parse_port


class PortAcceptanceTests(unittest.TestCase):
    def test_boundaries_are_valid(self) -> None:
        self.assertEqual(parse_port(1), 1)
        self.assertEqual(parse_port(65535), 65535)

    def test_values_below_range_are_rejected(self) -> None:
        for value in (0, -1, -65535):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_port(value)

    def test_values_above_range_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_port(65536)


if __name__ == "__main__":
    unittest.main()
