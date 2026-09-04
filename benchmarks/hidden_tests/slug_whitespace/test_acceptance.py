import unittest

from src.text_utils import slugify


class SlugAcceptanceTests(unittest.TestCase):
    def test_tabs_and_newlines_are_collapsed(self) -> None:
        self.assertEqual(slugify("One\tTwo\nThree"), "one-two-three")

    def test_empty_whitespace_returns_empty_slug(self) -> None:
        self.assertEqual(slugify("   "), "")


if __name__ == "__main__":
    unittest.main()
