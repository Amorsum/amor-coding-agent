import unittest

from src.parsing import parse_bool


class ParseBoolTests(unittest.TestCase):
    def test_false_text_is_false(self) -> None:
        self.assertIs(parse_bool(" false "), False)


if __name__ == "__main__":
    unittest.main()
