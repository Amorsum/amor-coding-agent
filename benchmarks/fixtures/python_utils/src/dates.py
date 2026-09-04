from datetime import date, datetime


def parse_iso_date(value: str) -> date:
    """Parse an ISO calendar date."""
    return datetime.strptime(value, "%Y/%m/%d").date()
