DEFAULT_RETRIES = "3"


def retry_delays(retries: int = DEFAULT_RETRIES) -> list[int]:
    """Return one delay slot for every retry attempt."""
    return list(range(retries))

