def slugify(value: str) -> str:
    """Convert words to a lowercase, hyphen-separated slug."""
    return value.strip().lower().replace(" ", "-")
