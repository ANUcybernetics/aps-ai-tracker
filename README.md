# Australian Government AI Transparency Tracker

This repository tracks **AI Transparency Statements** from Australian Government
agencies.

A _Cybernetic Studio_ project by [Ben Swift](https://benswift.me).

## Background

Under the
[Policy for the responsible use of AI in government](https://www.digital.gov.au/policy/ai/policy),
all Australian Government agencies are required (since Feb 28 2025) to publish
AI Transparency Statements on their websites. These statements must be updated
at least annually.

This project automatically scrapes these statements and stores them as markdown
files with YAML frontmatter, allowing changes to be tracked over time through
git. The list of agencies is from
[the APSC](https://www.apsc.gov.au/aps-agencies-size-and-function) with acronyms
cross-referenced from
[PM&C](https://www.pmc.gov.au/resources/abbreviations-and-acronyms-groups-or-topics).

## Usage

Run the scraper:

```bash
uv run scrape-ai-statements
```

The script will fetch all configured AI Transparency Statements and save them to
the `statements/` directory.

## Output format

Each statement is saved as a markdown file with YAML frontmatter containing:

- `agency_name`: Agency name
- `agency_abbr`: Agency abbreviation
- `source_url`: Original URL of the statement
- `final_url`: Final URL after redirects
- `fetched_at`: ISO 8601 timestamp of fetch
- `title`: Page title (extracted from HTML if available)
- `status_code`: HTTP status code
- `error`: Error message (if fetch failed, otherwise null)

## Adding new agencies

To add a new agency (because government's gonna MOG), edit `agencies.toml` and
add a new entry:

```toml
[[agencies]]
name = "Agency Name"
abbr = "ABBR"
size = "medium"  # small, medium, or large
url = "https://example.gov.au/ai-transparency-statement"
```

If the AI transparency statement URL is unknown or doesn't exist, set
`url = ""`. The scraper will skip agencies with empty URLs, but tests will fail
as a reminder to either find the URL or confirm none exists.

## Requirements

- `uv` (for Python package management)

That's it---dependencies are automatically installed by uv from
`pyproject.toml`.

## Author

(c) Ben Swift

## Contributing

If one of the URLs is wrong (or if you've got a URL for one of the
[missing agencies](./agencies.toml)) then I'd love to hear about it---either
submit a pull request or email me at
[ben.swift@anu.edu.au](mailto:ben.swift@anu.edu.au).

## License

This scraper code is licensed under the MIT License.

The scraped AI transparency statements themselves are copyright of their
respective Australian Government agencies. Most agency content is licensed under
[CC BY 4.0 Australia](https://creativecommons.org/licenses/by/4.0/) or
[CC BY 3.0 Australia](https://creativecommons.org/licenses/by/3.0/au/), though
individual agencies may use different licenses. Check each agency's website for
their specific copyright and licensing terms.
