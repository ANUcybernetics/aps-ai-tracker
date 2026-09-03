"""Check whether a manual agency's bot challenge falls to the browser fetch.

A manual agency costs a person a hand-check every `VERIFY_INTERVAL_DAYS`, so it
is worth knowing when one stops needing that. This asks the question without
answering it destructively: it fetches through the browser and reports what came
back, writing nothing and never failing the run that calls it. Promoting an
agency to `browser = true` stays a human decision, taken on a run of results
rather than one lucky night.
"""

import sys

from .scraper import Agency, fetch_raw_browser, load_agencies, logger


def describe(agency: Agency, error: str | None, size: int) -> str:
    """One line saying whether the browser reached this agency's statement."""
    outcome = f"blocked: {error}" if error else f"ok, {size} bytes"
    return f"{agency.abbr}\t{outcome}"


def main() -> int:
    """Probe each abbr named on the command line, or every manual agency."""
    wanted = {abbr.upper() for abbr in sys.argv[1:]}
    agencies = [
        a
        for a in load_agencies()
        if a.url is not None and (a.abbr in wanted if wanted else a.manual)
    ]
    if missing := wanted - {a.abbr for a in agencies}:
        logger.error(f"No agency with a URL for: {', '.join(sorted(missing))}")
        return 1

    for agency in agencies:
        result = fetch_raw_browser(agency)
        print(describe(agency, result["error"], len(result["content"] or b"")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
