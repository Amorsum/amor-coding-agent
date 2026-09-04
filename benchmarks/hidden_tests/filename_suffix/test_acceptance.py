import unittest

from src.filenames import suffix


class FilenameAcceptanceTests(unittest.TestCase):
    def test_name_without_suffix_returns_empty(self) -> None:
        self.assertEqual(suffix("README"), "")

    def test_dotfile_returns_empty(self) -> None:
        self.assertEqual(suffix(".env"), "")


if __name__ == "__main__":
    unittest.main()
