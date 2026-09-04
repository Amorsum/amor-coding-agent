import unittest
from datetime import date

from src.dates import parse_iso_date


class DateTests(unittest.TestCase):
    def test_parses_iso_format(self) -> None:
        self.assertEqual(parse_iso_date("2026-09-03"), date(2026, 9, 3))


if __name__ == "__main__":
    unittest.main()
