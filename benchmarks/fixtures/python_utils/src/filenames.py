def suffix(name: str) -> str:
    """Return the final filename suffix without its dot."""
    return name.split(".", 1)[-1]
