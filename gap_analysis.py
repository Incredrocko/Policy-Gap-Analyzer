"""Task 1: check the policy under review against every NIST CSF requirement
mapped to its domain, batched into LLM calls of config.REQUIREMENTS_BATCH_SIZE
requirements each, with retry-on-malformed-or-incomplete-response."""
import json
import re

import config
import ollama_client
import prompts
import reference_data


def _parse_gap_json(raw: str) -> dict:
    """Defensive JSON parsing -- small local models sometimes wrap JSON in
    markdown fences or add stray text despite format='json'."""
    text = raw.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {"results": [], "_parse_error": True, "_raw": raw}


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _call_batch(batch: list[dict], policy_text: str) -> list[dict]:
    """Runs one batch of requirements through the LLM, retrying (with a
    corrective note appended to the prompt) if the response is malformed or
    missing verdicts for some ids. Always returns exactly one result per
    requirement in `batch`, in the same order -- unresolved ids after
    retries are filled with a clearly-marked "unverified" placeholder rather
    than silently dropped, so a flaky model run can't quietly under-report
    gaps."""
    ids_expected = [r["id"] for r in batch]
    req_payload = [
        {"id": r["id"], "function": r["function"], "category": r["category"],
         "requirement": r["description"]}
        for r in batch
    ]
    base_prompt = prompts.GAP_ANALYSIS_USER_TEMPLATE.format(
        policy_text=policy_text,
        requirements_json=json.dumps(req_payload, indent=2),
    )

    results_by_id: dict[str, dict] = {}
    prompt = base_prompt
    for attempt in range(config.MAX_LLM_RETRIES + 1):
        raw = ollama_client.chat(prompt, system=prompts.GAP_ANALYSIS_SYSTEM, json_mode=True)
        parsed = _parse_gap_json(raw)
        for r in parsed.get("results", []):
            rid = r.get("id")
            if rid in ids_expected and rid not in results_by_id:
                results_by_id[rid] = r

        missing = [i for i in ids_expected if i not in results_by_id]
        if not missing:
            break
        if attempt < config.MAX_LLM_RETRIES:
            prompt = base_prompt + (
                f"\n\nYour previous response was missing or malformed results for "
                f"these requirement ids: {missing}. Return a complete JSON object "
                f"with exactly one result for every id listed above, including these."
            )

    for rid in ids_expected:
        if rid not in results_by_id:
            results_by_id[rid] = {
                "id": rid,
                "status": "not_covered",
                "severity": "medium",
                "description": (
                    "The model did not return a verdict for this requirement after "
                    f"{config.MAX_LLM_RETRIES + 1} attempts -- treat as unverified, "
                    "not a confirmed gap."
                ),
                "policy_reference": "none",
                "_verdict_missing": True,
            }

    return [results_by_id[i] for i in ids_expected]


def analyze_policy(policy_text: str, domain: str) -> dict:
    """Returns {"domain", "requirements_checked", "gaps": [...], "adequate": [...],
    "unverified_count": int}. Each gap/adequate item merges the LLM's verdict with
    the original requirement record (id, function, category, description,
    matched_policies)."""
    requirements = reference_data.get_domain_requirements(domain)
    if not requirements:
        raise ValueError(f"No requirements resolved for domain '{domain}'.")

    by_id = {r["id"]: r for r in requirements}
    gaps, adequate = [], []
    unverified_count = 0

    for batch in _chunked(requirements, config.REQUIREMENTS_BATCH_SIZE):
        results = _call_batch(batch, policy_text)

        for result in results:
            req = by_id.get(result.get("id"))
            if req is None:
                continue  # shouldn't happen -- _call_batch only returns expected ids
            if result.get("_verdict_missing"):
                unverified_count += 1
            # Both req and result have a "description" key (NIST requirement text
            # vs. the LLM's gap verdict text) -- keep both under distinct names.
            merged = {**req, "requirement": req["description"], **result}

            if result.get("status") == "covered":
                adequate.append(merged)
            else:
                gaps.append(merged)

    return {
        "domain": domain,
        "requirements_checked": len(requirements),
        "gaps": gaps,
        "adequate": adequate,
        "unverified_count": unverified_count,
    }


def render_gap_report(analysis: dict) -> str:
    lines = [
        "# Policy Gap Analysis Report",
        f"**Domain:** {analysis['domain']}",
        f"**Requirements checked:** {analysis['requirements_checked']}",
        f"**Gaps identified:** {len(analysis['gaps'])}",
        f"**Adequately covered:** {len(analysis['adequate'])}",
    ]
    if analysis.get("unverified_count"):
        lines.append(
            f"**⚠ Unverified (model didn't return a verdict after retries):** "
            f"{analysis['unverified_count']} -- these are counted as gaps below but "
            f"flagged separately; re-run or check manually."
        )
    lines.append("")

    if analysis["gaps"]:
        lines.append("## Gaps Identified\n")
        by_function: dict[str, list] = {}
        for g in analysis["gaps"]:
            by_function.setdefault(g["function"], []).append(g)
        for function, items in by_function.items():
            lines.append(f"### {function}")
            for g in items:
                sev = (g.get("severity") or "?").upper()
                status = g.get("status", "not_covered")
                flag = " ⚠ UNVERIFIED" if g.get("_verdict_missing") else ""
                lines.append(
                    f"- **[{sev} / {status.upper()}]{flag} {g['id']} ({g['category']})**\n"
                    f"  - *NIST requirement:* {g.get('requirement', '')}\n"
                    f"  - *Assessment:* {g.get('description', '')}\n"
                    f"  - *Applies to:* {', '.join(g.get('matched_policies', []))}"
                )
            lines.append("")
    else:
        lines.append("_No gaps identified._\n")

    if analysis["adequate"]:
        lines.append("## Adequately Covered Requirements\n")
        for a in analysis["adequate"]:
            lines.append(
                f"- **{a['id']}** ({a['category']}) — {a.get('requirement', '')} "
                f"_(assessment: {a.get('description', '')})_"
            )

    return "\n".join(lines)
