from src.tax import calculate_tax


def invoice_total(items: list[float], tax_rate: float) -> float:
    """Return the subtotal plus tax."""
    subtotal = sum(items)
    return subtotal
