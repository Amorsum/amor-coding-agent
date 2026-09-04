import unittest

from src.filenames import suffix


class FilenameTests(unittest.TestCase):
    def test_uses_final_suffix(self) -> None:
        self.assertEqual(suffix("archive.tar.gz"), "gz")


if __name__ == "__main__":
    unittest.main()
