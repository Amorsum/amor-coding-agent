import unittest

from src.invoices import invoice_total


class InvoiceAcceptanceTests(unittest.TestCase):
    def test_zero_rate_preserves_subtotal(self) -> None:
        self.assertEqual(invoice_total([10.0, 15.0], 0.0), 25.0)

    def test_invalid_rate_uses_tax_validation(self) -> None:
        with self.assertRaises(ValueError):
            invoice_total([10.0], 1.1)


if __name__ == "__main__":
    unittest.main()
