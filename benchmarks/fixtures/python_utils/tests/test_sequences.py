import unittest

from src.sequences import chunks, unique_in_order


class SequenceTests(unittest.TestCase):
    def test_chunks_retain_remainder(self) -> None:
        self.assertEqual(chunks([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_unique_values_keep_first_seen_order(self) -> None:
        self.assertEqual(unique_in_order([3, 1, 3, 2]), [3, 1, 2])


if __name__ == "__main__":
    unittest.main()
