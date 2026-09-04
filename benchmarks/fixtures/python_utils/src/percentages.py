def clamp_percentage(value: float) -> float:
    """Clamp a percentage to the inclusive range 0 through 100."""
    return min(value, 100.0)
