"""Central configuration. Override CLI-relevant bits via main.py flags."""
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

REFERENCE_PDF = DATA_DIR / "reference_guide.pdf"
NIST_MAPPING_JSON = DATA_DIR / "nist_csf_mapping.json"

OLLAMA_HOST = "http://localhost:11434"
CHAT_MODEL = "llama3.2:3b"       # swap for qwen2.5:3b, phi3:mini, etc.

# Gap-analysis calls return short JSON and finish quickly. Revision and
# roadmap calls generate a full rewritten document and can genuinely take
# several minutes on CPU-only hardware with a 3B model -- 300s was too
# tight and was cutting off real (if slow) generations. Raise this further
# if you're on a slower machine or a larger model.
OLLAMA_TIMEOUT_SECONDS = 900

# How many NIST CSF requirements to check per LLM call. A lightweight 3B
# model's instruction-following degrades with too many items in one JSON
# response -- 8-12 is a reasonable batch size. Larger models can go higher.
REQUIREMENTS_BATCH_SIZE = 10

# If a batch comes back with malformed JSON or missing verdicts for some
# requirement ids, how many extra attempts to make (with a corrective note
# appended to the prompt) before falling back to a "not_covered / unverified"
# placeholder for whatever's still missing.
MAX_LLM_RETRIES = 2

# --- Domain -> reference policy template mapping ------------------------
# The reference guide maps NIST CSF subcategories to its own set of ~36
# policy/standard template names (see build_reference_data.py output). The
# four domains named in the problem statement (ISMS, Data Privacy and
# Security, Patch Management, Risk Management) don't appear verbatim in the
# guide, so this mapping is a judgment call -- sanity-check it against the
# actual dummy policies you write, and adjust freely. It is not derived from
# the source document; it's this scaffold's interpretation of which
# reference template names best correspond to each domain.
DOMAIN_POLICY_MAP = {
    "Information Security Management System (ISMS)": [
        "Information Security Policy",
        "Information Security Risk Management",
        "Security Assessment and Authorization Policy",
        "Systems and Services Acquisition Policy",
        "Planning Policy",
        "Personnel Security Policy",
        "Security Awareness and Training Policy",
        "Acceptable Use of Information Technology Resource Policy",
    ],
    "Data Privacy and Security": [
        "Encryption Standard",
        "Media Protection Policy",
        "Information Classification Standard",
        "Mobile Device Security",
        "System and Communications Protection Policy",
        "Sanitization Secure Disposal Standard",
        "Identification and Authentication Policy",
    ],
    "Patch Management": [
        "Patch Management Standard",
        "Maintenance Policy",
        "Configuration Management Policy",
        "Secure Configuration Standard",
        "Vulnerability Scanning Standard",
    ],
    "Risk Management": [
        "Standard Risk Assessment Policy",
        "Information Security Risk Management",
        "Vulnerability Scanning Standard",
        "Auditing and Accountability Standard",
        "Security Logging Standard",
        "System and Information Integrity Policy",
    ],
}

POLICY_DOMAINS = list(DOMAIN_POLICY_MAP.keys())
