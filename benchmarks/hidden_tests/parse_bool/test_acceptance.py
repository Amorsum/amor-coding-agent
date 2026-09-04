import unittest

from src.parsing import parse_bool


class ParseBoolAcceptanceTests(unittest.TestCase):
    def test_true_is_case_insensitive(self) -> None:
        self.assertIs(parse_bool(" TRUE "), True)

    def test_unknown_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_bool("yes")


if __name__ == "__main__":
    unittest.main()
