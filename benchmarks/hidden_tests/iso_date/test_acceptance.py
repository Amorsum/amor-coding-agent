import unittest
from datetime import date

from src.dates import parse_iso_date


class DateAcceptanceTests(unittest.TestCase):
    def test_leap_day_is_parsed(self) -> None:
        self.assertEqual(parse_iso_date("2024-02-29"), date(2024, 2, 29))

    def test_invalid_date_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_iso_date("2025-02-29")


if __name__ == "__main__":
    unittest.main()
