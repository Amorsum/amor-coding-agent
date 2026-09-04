def remaining_stock(stock: int, requested: int) -> int:
    """Return remaining stock for a valid requested quantity."""
    if requested > stock:
        raise ValueError("requested quantity exceeds stock")
    return stock - requested
