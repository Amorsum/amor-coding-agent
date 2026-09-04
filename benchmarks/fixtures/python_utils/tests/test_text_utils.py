import unittest

from src.text_utils import slugify


class SlugifyTests(unittest.TestCase):
    def test_collapses_surrounding_and_repeated_whitespace(self) -> None:
        self.assertEqual(slugify("  Hello   World  "), "hello-world")


if __name__ == "__main__":
    unittest.main()
