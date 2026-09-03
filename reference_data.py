"""Loads the parsed NIST CSF subcategory mapping and resolves it against a
policy domain (via config.DOMAIN_POLICY_MAP) to get the specific list of
requirements that domain's policy should satisfy."""
import json

import config


def load_mapping() -> list[dict]:
    if not config.NIST_MAPPING_JSON.exists():
        raise FileNotFoundError(
            f"{config.NIST_MAPPING_JSON} not found. Run `python build_reference_data.py` "
            "first (requires data/reference_guide.pdf to be present)."
        )
    return json.loads(config.NIST_MAPPING_JSON.read_text())


def get_domain_requirements(domain: str) -> list[dict]:
    """Returns the subcategory entries whose 'policies' list overlaps with the
    reference-template names mapped to this domain in config.DOMAIN_POLICY_MAP.

    Each returned entry also gets a 'matched_policies' key showing which of
    its reference template names triggered the match, so the gap report can
    show its work.
    """
    target_names = set(config.DOMAIN_POLICY_MAP.get(domain, []))
    if not target_names:
        raise ValueError(
            f"No policy template names mapped for domain '{domain}'. "
            f"Add an entry to config.DOMAIN_POLICY_MAP. Known domains: "
            f"{list(config.DOMAIN_POLICY_MAP.keys())}"
        )

    mapping = load_mapping()
    matched = []
    for entry in mapping:
        overlap = target_names & set(entry["policies"])
        if overlap:
            matched.append({**entry, "matched_policies": sorted(overlap)})
    return matched
