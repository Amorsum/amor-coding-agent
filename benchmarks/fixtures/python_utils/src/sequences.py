def chunks(values: list[int], size: int) -> list[list[int]]:
    """Split values into chunks and retain the final partial chunk."""
    if size < 1:
        raise ValueError("size must be positive")
    return [values[index:index + size] for index in range(0, len(values) - size + 1, size)]


def unique_in_order(values: list[int]) -> list[int]:
    """Remove duplicates while preserving first-seen order."""
    return sorted(set(values))
