from src.pricing import apply_discount


def order_total(prices: list[float], discount_rate: float = 0.0) -> float:
    """Return the final total after applying a discount."""
    subtotal = sum(prices)
    return subtotal

