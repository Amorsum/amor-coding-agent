def validate_timeout(seconds: int) -> int:
    """Validate and return a positive timeout."""
    if seconds < 0:
        raise ValueError("timeout must be positive")
    return seconds
