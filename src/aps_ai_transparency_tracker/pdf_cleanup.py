"""LLM-based cleanup of PDF-extracted markdown, gated on raw-content hash."""

import hashlib
import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

CLEANUP_MODEL = "claude-haiku-4-5"
CLEANUP_PROMPT = """You are cleaning up text extracted from a PDF AI transparency statement so it renders cleanly as markdown.

Apply these transformations and nothing else:
- Remove repeated "OFFICIAL", "OFFICIAL: Sensitive", and "Classification:" markers
- Remove standalone page numbers and headers/footers like "Page N of M"
- Remove dotted leader lines from tables of contents (e.g. "Introduction ........ 2")
- Reflow paragraphs that were broken across PDF lines into normal prose
- Convert obvious headings to markdown headings (#, ##, ###) based on context
- Convert obvious bullet lists (lines starting with •, -, *, or numbered) to markdown lists

Do NOT:
- Add, remove, or rephrase any factual content
- Add commentary, headers, or footers of your own
- Wrap the output in code fences or quotes
- Translate or summarise

Output the cleaned markdown directly with no preamble."""


def _cache_path(abbr: str, raw_dir: Path) -> Path:
    return raw_dir / f"{abbr}.pdf-clean.json"


def clean_pdf_markdown(raw_text: str, abbr: str, raw_dir: Path) -> str:
    """Return LLM-cleaned markdown for a PDF, cached by raw-content hash.

    Re-runs the LLM only when the raw extracted text has changed since the
    last cleanup. Returns the raw text unchanged if no API key is configured
    or the LLM call fails.
    """
    raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    cache_file = _cache_path(abbr, raw_dir)

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("raw_hash") == raw_hash:
                logger.info(f"Using cached PDF cleanup for {abbr}")
                return cached["cleaned"]
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"Invalid cache file for {abbr}, regenerating")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning(
            f"ANTHROPIC_API_KEY not set; skipping LLM cleanup for {abbr}"
        )
        return raw_text

    logger.info(f"Running LLM cleanup for {abbr} PDF...")
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=CLEANUP_MODEL,
            max_tokens=16000,
            system=CLEANUP_PROMPT,
            messages=[{"role": "user", "content": raw_text}],
        )
        cleaned = next(
            (b.text for b in response.content if b.type == "text"), raw_text
        ).strip()
    except anthropic.AnthropicError as e:
        logger.error(f"LLM cleanup failed for {abbr}: {e}; using raw text")
        return raw_text

    cache_file.write_text(
        json.dumps({"raw_hash": raw_hash, "cleaned": cleaned}), encoding="utf-8"
    )
    return cleaned
