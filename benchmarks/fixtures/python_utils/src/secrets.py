def redact_secret(value: str) -> str:
    """Return a display-safe representation of a secret."""
    return value[:4] + "..."
