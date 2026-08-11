"""
PDF parsing and hierarchical, section-aware chunking.

Design rationale (see Pipeman Design Document, Section 2):
Policy/issuance PDFs are chunked along document structure (headings and
sections), not by a fixed character count, so each chunk can carry a full
hierarchical citation path (e.g. "DoD > DLA > DLA Energy > Quality >
QSMV Checklist") rather than just a page number.

This module uses a heuristic heading detector suitable for a personal
sandbox with clean public PDFs. For messier or scanned enterprise
documents (the real DGEE catalog), replace `extract_pages_with_headings`
with a call to Document AI's Layout Parser, which detects headings more
reliably from visual structure. The rest of this module (chunking,
hierarchy tracking) does not need to change.
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from pypdf import PdfReader

from ingestion.config import config

# Heuristic heading patterns: numbered sections ("1.", "1.1", "Section 4"),
# short ALL-CAPS lines, or lines ending without a period that look like titles.
HEADING_PATTERNS = [
    re.compile(r"^\s*(\d+(\.\d+)*)\s+[A-Z].{0,80}$"),
    re.compile(r"^\s*SECTION\s+\d+.{0,80}$", re.IGNORECASE),
    re.compile(r"^[A-Z][A-Z0-9 \-/&,]{6,70}$"),
]


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 90:
        return False
    return any(p.match(line) for p in HEADING_PATTERNS)


def _heading_level(line: str) -> int:
    """Rough heading depth from a numbered prefix, e.g. '2.1.3' -> level 3."""
    match = re.match(r"^\s*(\d+(\.\d+)*)", line)
    if match:
        return match.group(1).count(".") + 1
    return 1


@dataclass
class Chunk:
    text: str
    hierarchy_path: str
    source_document: str
    page_number: int
    chunk_index: int
    metadata: dict = field(default_factory=dict)


def extract_lines_with_pages(pdf_path: str) -> list[tuple[str, int]]:
    """Returns a flat list of (line_text, page_number) tuples."""
    reader = PdfReader(pdf_path)
    lines: list[tuple[str, int]] = []
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for line in text.split("\n"):
            if line.strip():
                lines.append((line, page_num))
    return lines


def build_hierarchical_chunks(
    pdf_path: str,
    source_document: str,
    root_path: str = "DoD > DLA",
) -> list[Chunk]:
    """
    Walks the document, tracks a heading stack to build each chunk's
    hierarchy_path, and splits section text into ~MAX_CHUNK_CHARS pieces
    without ever crossing a heading boundary.
    """
    lines = extract_lines_with_pages(pdf_path)
    heading_stack: list[str] = []
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_start_page = 1
    chunk_index = 0

    def flush_buffer(end_page: int):
        nonlocal buffer, chunk_index
        text = " ".join(buffer).strip()
        buffer = []
        if not text:
            return
        path = " > ".join([root_path] + heading_stack) if heading_stack else root_path
        # Split long section text into overlapping windows so no single
        # chunk exceeds the target size, while keeping the same hierarchy_path.
        start = 0
        while start < len(text):
            end = min(start + config.MAX_CHUNK_CHARS, len(text))
            piece = text[start:end]
            chunks.append(
                Chunk(
                    text=piece,
                    hierarchy_path=path,
                    source_document=source_document,
                    page_number=end_page,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
            if end == len(text):
                break
            start = end - config.CHUNK_OVERLAP_CHARS

    current_page = 1
    for line, page_num in lines:
        current_page = page_num
        if _looks_like_heading(line):
            flush_buffer(current_page)
            level = _heading_level(line)
            heading_text = line.strip()
            heading_stack = heading_stack[: level - 1] + [heading_text]
        else:
            buffer.append(line.strip())
    flush_buffer(current_page)

    return chunks
