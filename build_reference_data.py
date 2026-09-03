"""One-time parser: turns the CIS/MS-ISAC NIST CSF Policy Template Guide PDF into
structured JSON (data/nist_csf_mapping.json).

The guide isn't prose — it's a table: for each of ~99 NIST CSF subcategories
(e.g. "GV.OC-01"), a one-sentence requirement description, followed by a
bullet list of policy/standard template names that address it. That structure
is exactly what makes generic text-chunking + embedding retrieval the wrong
tool here: there's no free text to search semantically, just a lookup table.
So we parse it once into JSON and use it directly (see reference_data.py).

Run standalone:
    python build_reference_data.py
Regenerates data/nist_csf_mapping.json from data/reference_guide.pdf.

TODO: the source PDF itself has a couple of data-quality quirks worth knowing
about before you trust it blindly: GV.OC-04 and GV.OC-05 have identical
description text (looks like a copy-paste error in CIS's original document),
and one entry is numbered "RS.CO-3" instead of "RS.CO-03" (inconsistent
zero-padding) which this parser's regex (requiring 2 digits) will silently
merge into the preceding entry's description rather than drop entirely.
Decide whether you want a stricter or looser ID regex depending on how much
that one entry matters to your gap analysis.
"""
import json
import re

import config
from pdf_utils import extract_pdf_text

SUBCAT_RE = re.compile(r'^([A-Z]{2}\.[A-Z]{2,3}-\d{2})\s*(.*)$')
CATEGORY_RE = re.compile(r'^([A-Za-z][A-Za-z ,]+):\s*([A-Za-z][A-Za-z ,\-]+?)\s*\(([A-Z]{2}\.[A-Z]{2,3})\s*\)$')

# Text that marks the start of the actual content (skips the table of contents,
# which contains lines that would otherwise false-match CATEGORY_RE).
CONTENT_START_MARKER = "NIST FUNCTION:\nGovern\nGovern: Organizational Context"


def parse_reference_pdf(pdf_path) -> list[dict]:
    raw = extract_pdf_text(pdf_path)
    # extract_pdf_text adds "[[PAGE N]]" markers per page — strip for parsing
    raw = re.sub(r"\[\[PAGE \d+\]\]\n?", "", raw)

    start = raw.find(CONTENT_START_MARKER)
    if start == -1:
        raise ValueError(
            "Could not find expected content start marker in the PDF text. "
            "The document structure may differ from what this parser expects — "
            "inspect the raw extraction (extract_pdf_text) and adjust the regexes."
        )
    text = raw[start:]
    lines = text.split("\n")

    entries: list[dict] = []
    current_function = None
    current_category = None
    current_category_code = None
    current = None

    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        i += 1

        if not line or line.isdigit():
            continue
        if "NIST Cybersecurity Framework: Policy Template Guide" in line:
            continue
        if line.startswith("NIST FUNCTION:"):
            while i < n and not lines[i].strip():
                i += 1
            current_function = lines[i].strip()
            i += 1
            continue

        m_cat = CATEGORY_RE.match(line)
        if m_cat:
            current_category = m_cat.group(2).strip()
            current_category_code = m_cat.group(3).strip()
            continue

        m_sub = SUBCAT_RE.match(line)
        if m_sub:
            if current:
                entries.append(current)
            current = {
                "id": m_sub.group(1),
                "function": current_function,
                "category": current_category,
                "category_code": current_category_code,
                "description": m_sub.group(2).strip(),
                "policies": [],
            }
            continue

        if line.startswith("•"):
            if current is not None:
                current["policies"].append(line.lstrip("•").strip())
            continue

        # Continuation of a wrapped description line — only before any bullets
        # have been seen for the current entry; anything after that point is
        # page header/footer noise and gets dropped.
        if current is not None and not current["policies"]:
            current["description"] = (current["description"] + " " + line).strip()

    if current:
        entries.append(current)

    return entries


def main():
    entries = parse_reference_pdf(config.REFERENCE_PDF)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.NIST_MAPPING_JSON.write_text(json.dumps(entries, indent=2))
    print(f"Parsed {len(entries)} subcategory entries -> {config.NIST_MAPPING_JSON}")

    all_policy_names = sorted({p for e in entries for p in e["policies"]})
    print(f"\n{len(all_policy_names)} distinct policy template names referenced:")
    for p in all_policy_names:
        print(f"  - {p}")
    print(
        "\nCheck these against config.DOMAIN_POLICY_MAP — if you add a new policy "
        "domain, map it to the relevant names from this list."
    )


if __name__ == "__main__":
    main()
