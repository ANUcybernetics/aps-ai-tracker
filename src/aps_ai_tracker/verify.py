"""List manual agencies overdue for a hand-check against their live page.

Manual agencies are fetched by nobody (see `manual_reason` in agencies.toml),
so the only thing standing between their statement and silent rot is a person
opening the page. This prints the ones due, tab-separated, for the nightly run
to turn into todos; it deliberately knows nothing about where those todos go.
"""

import sys
from datetime import UTC, date, datetime, timedelta

from .scraper import Agency, load_agencies

# Long enough not to nag, short enough that a missed change is still news.
VERIFY_INTERVAL_DAYS = 30


def overdue(agencies: list[Agency], today: date) -> list[Agency]:
    """Manual agencies never verified, or verified longer ago than the interval."""
    cutoff = today - timedelta(days=VERIFY_INTERVAL_DAYS)
    due = []
    for agency in agencies:
        if not agency.manual:
            continue
        if (
            agency.last_verified is None
            or date.fromisoformat(agency.last_verified) <= cutoff
        ):
            due.append(agency)
    return due


def main() -> int:
    """Print one overdue agency per line as `abbr<TAB>name<TAB>url`."""
    for agency in overdue(load_agencies(), datetime.now(UTC).date()):
        print(f"{agency.abbr}\t{agency.name}\t{agency.url or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
