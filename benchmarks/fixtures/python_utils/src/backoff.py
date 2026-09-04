def backoff_delay(attempt: int, base_seconds: int = 1) -> int:
    """Return an exponential retry delay for a zero-based attempt."""
    return base_seconds * attempt
