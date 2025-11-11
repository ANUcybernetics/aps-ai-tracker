---
id: task-1
title: Python Best Practices Audit Results
status: To Do
assignee: []
created_date: "2025-11-11 06:46"
labels: [audit, improvements]
dependencies: []
---

# Python Best Practices Audit - Recommendations

Audit completed: 2025-11-11

## Summary Assessment

**Overall:** Code is well-structured and follows modern Python practices. Passes
ruff linting with zero issues, has solid test coverage, and uses appropriate
modern libraries.

**Key findings:** 8 recommendations across 3 priority levels. Focus on the 3
high-priority robustness improvements for production cron job usage.

---

## High Priority (Implement Soon)

### 1. Add retry logic for network requests

**Location:** `scraper.py:71` in `fetch_statement()`

**Issue:** Currently does single HTTP request with no retry on transient
failures, making the scraper fragile for cron job usage.

**Implementation:**

- Add 3 retries with exponential backoff (2^attempt seconds)
- Retry on `httpx.TimeoutException` and `httpx.NetworkError`
- Don't retry 4xx errors (client errors, not transient)
- Log each retry attempt

**Estimated effort:** 30 minutes

---

### 2. Implement granular exception handling

**Location:** `scraper.py:99-106` in `fetch_statement()`

**Issue:** Broad `except Exception` catches everything including bugs in our own
code, making debugging harder.

**Implementation:**

- Catch `httpx.TimeoutException`, `httpx.NetworkError`, `httpx.HTTPError`
  separately
- Catch parsing exceptions (`UnicodeDecodeError`, `ValueError`) separately
- Use `logger.exception()` for truly unexpected errors to capture stack traces
- Different error messages for network vs parsing vs unexpected errors

**Estimated effort:** 20 minutes

---

### 3. Add PDF extraction validation

**Location:** `scraper.py:83` in `fetch_statement()`

**Issue:** `pypdf.PdfReader.extract_text()` can return empty strings for scanned
PDFs, leading to silent failures.

**Implementation:**

- Validate each page has text content
- Log warnings for pages with no extractable text
- Return error if entire PDF has no extractable text
- Helps identify image-based PDFs that need OCR

**Estimated effort:** 30 minutes

---

## Medium Priority (Next Iteration)

### 4. Use TypedDict for fetch_statement return value

**Location:** `scraper.py:69`

**Issue:** Return type `dict[str, str | int | None]` lacks structure validation,
making it easy to typo field names.

**Implementation:**

```python
from typing import TypedDict

class StatementResult(TypedDict):
    title: str | None
    markdown: str | None
    status_code: int | None
    final_url: str
    error: str | None

def fetch_statement(agency: Agency) -> StatementResult:
    ...
```

**Benefits:** Better type checking, IDE autocomplete, self-documenting

**Estimated effort:** 15 minutes

---

### 5. Move logging configuration to **main**.py

**Location:** `scraper.py:13-16`

**Issue:** `logging.basicConfig()` at module import time can conflict with other
logging setups if this is ever used as a library.

**Implementation:**

- Move `basicConfig()` call to `main()` in `__main__.py`
- Keep `logger = logging.getLogger(__name__)` in `scraper.py`
- Makes the module more library-friendly

**Estimated effort:** 10 minutes

---

## Low Priority (Optional Enhancements)

### 6. Add edge case tests

**Current state:** Test coverage is already very good (13 passing tests)

**Optional additions:**

- Test extremely large HTML pages (>1MB)
- Test malformed YAML in frontmatter edge cases
- Test concurrent scraping scenarios

**Estimated effort:** 1-2 hours

---

### 7. Add HTTP connection pooling

**Location:** `scraper.py:71` and `__main__.py:12`

**Issue:** Creating new connection for each of 110 agencies is slower than
reusing connections.

**Implementation:**

```python
# In __main__.py
with httpx.Client(...) as client:
    for agency in agencies:
        fetch_statement(agency, client)
```

**Benefits:** Faster scraping, reduced resource usage

**When to implement:** Only if scraping time becomes an issue (currently
acceptable)

**Estimated effort:** 20 minutes

---

### 8. Consider switching from NamedTuple to dataclass

**Location:** `scraper.py:18-23` (Agency class)

**Current state:** `NamedTuple` is lightweight and appropriate for this use case

**Alternative:**

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Agency:
    name: str
    abbr: str
    url: str | None
```

**When to switch:** Only if you need validation, default values, or methods

**Estimated effort:** 5 minutes (but not necessary)

---

## What's Already Good

The following are already following best practices:

- ✓ Dependency choices (httpx, beautifulsoup4, pypdf, etc.)
- ✓ Custom User-Agent header
- ✓ HTTPS enforcement (all URLs are HTTPS)
- ✓ HTML parsing with defensive fallbacks
- ✓ Test organization and pytest markers
- ✓ Code style (passes ruff with zero issues)
- ✓ Type hints throughout
- ✓ Project structure and separation of concerns

---

## Implementation Priority

**Total recommended changes:** 8 tasks across 3 priority levels

**Time to implement high priority items:** ~1.5 hours

**Time to implement all medium priority items:** ~2 hours total

**Core recommendation:** Focus on the 3 high-priority robustness improvements
(retry logic, exception handling, PDF validation). These will make the scraper
significantly more reliable for production cron job usage.
