import unittest

from src.invoices import invoice_total


class InvoiceTests(unittest.TestCase):
    def test_tax_is_added_to_subtotal(self) -> None:
        self.assertEqual(invoice_total([40.0, 60.0], 0.2), 120.0)


if __name__ == "__main__":
    unittest.main()
