def apply_discount(subtotal: float, discount_rate: float) -> float:
    """Apply a fractional discount to a subtotal."""
    if not 0.0 <= discount_rate <= 1.0:
        raise ValueError("discount_rate must be between 0 and 1")
    return subtotal * (1.0 - discount_rate)

