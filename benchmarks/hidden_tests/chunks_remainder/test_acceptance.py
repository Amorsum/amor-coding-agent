import unittest

from src.sequences import chunks


class ChunkAcceptanceTests(unittest.TestCase):
    def test_short_input_is_retained(self) -> None:
        self.assertEqual(chunks([1], 3), [[1]])

    def test_non_positive_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            chunks([1], 0)


if __name__ == "__main__":
    unittest.main()
