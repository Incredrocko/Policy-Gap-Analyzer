"""Text extraction from the reference PDF and from policy documents
(PDF, .docx, or plain .txt)."""
from pathlib import Path

from pypdf import PdfReader


def extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF, page by page, joined with page-break markers.

    TODO: this is plain text extraction only. If the reference guide or a
    policy has tables or multi-column layout, pypdf will interleave columns
    incorrectly. Swap in pdfplumber if that turns out to matter.
    """
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append(f"\n\n[[PAGE {i + 1}]]\n{text}")
    return "".join(pages)


def load_policy_text(path: Path) -> str:
    """Load the organizational policy under review. Supports .pdf, .docx, .txt/.md."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".docx":
        import docx  # python-docx

        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported policy file type: {suffix}")


def split_policy_into_sections(text: str) -> list[dict]:
    """Naive section splitter for the policy under review: splits on lines that
    look like headings (numbered, ALL CAPS, or Markdown '#').

    Not currently used by the default pipeline (gap_analysis.py sends the
    whole policy text per batch) -- kept here for when you need to chunk a
    long real-world policy instead of a short dummy one. See README
    Limitations.

    Returns a list of {"heading": str, "text": str}. Falls back to a single
    section named "Full Policy" if no headings are detected.

    TODO: tune this once you see real dummy-policy formatting. Consider using
    the LLM itself to segment if the heuristic is too fragile.
    """
    import re

    lines = text.splitlines()
    heading_pattern = re.compile(
        r"^\s*(#{1,3}\s+.+|(\d+(\.\d+)*)[\.\)]\s+[A-Z].{2,80}|[A-Z][A-Z \-/&]{4,80})\s*$"
    )

    sections: list[dict] = []
    current_heading = "Preamble"
    current_lines: list[str] = []

    for line in lines:
        if heading_pattern.match(line.strip()) and len(line.strip()) < 100:
            if current_lines:
                sections.append(
                    {"heading": current_heading, "text": "\n".join(current_lines).strip()}
                )
            current_heading = line.strip().lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({"heading": current_heading, "text": "\n".join(current_lines).strip()})

    sections = [s for s in sections if s["text"].strip()]
    if not sections:
        sections = [{"heading": "Full Policy", "text": text}]
    return sections
