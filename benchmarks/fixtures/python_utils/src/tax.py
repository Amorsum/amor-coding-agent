def calculate_tax(subtotal: float, rate: float) -> float:
    """Calculate tax after validating a fractional rate."""
    if not 0.0 <= rate <= 1.0:
        raise ValueError("rate must be between 0 and 1")
    return subtotal * rate
