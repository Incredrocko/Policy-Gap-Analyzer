"""Task 2: revise the policy to close identified gaps, produce a prioritized
improvement roadmap, and (for the evaluation harness) judge whether the
revision actually addressed each gap."""
import json
import re

import ollama_client
import prompts


def revise_policy(original_policy_text: str, analysis: dict) -> str:
    gaps = analysis["gaps"]
    if not gaps:
        return original_policy_text + "\n\n_(No gaps identified -- policy left unchanged.)_"

    user_prompt = prompts.REVISION_USER_TEMPLATE.format(
        original_policy=original_policy_text,
        gaps_json=json.dumps(gaps, indent=2),
    )
    return ollama_client.chat(user_prompt, system=prompts.REVISION_SYSTEM, temperature=0.3)


def generate_roadmap(analysis: dict) -> str:
    gaps = analysis["gaps"]
    if not gaps:
        return "# Improvement Roadmap\n\nNo gaps identified -- no roadmap items."

    user_prompt = prompts.ROADMAP_USER_TEMPLATE.format(gaps_json=json.dumps(gaps, indent=2))
    return ollama_client.chat(user_prompt, system=prompts.ROADMAP_SYSTEM, temperature=0.3)


def _parse_judge_json(raw: str) -> dict:
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
    return {"verdicts": [], "overall_score": None, "_parse_error": True, "_raw": raw}


def judge_revision(revised_policy_text: str, analysis: dict) -> dict:
    """LLM-as-judge pass: independently checks whether the revision actually
    closed each identified gap, rather than trusting the revision step's own
    output. Used by evaluate.py; not part of the default main.py run since it
    doubles the LLM calls for a single-shot use of the tool."""
    gaps = analysis["gaps"]
    if not gaps:
        return {"verdicts": [], "overall_score": 5, "addressed_count": 0, "total": 0}

    # Judge against a slim view of each gap -- id/requirement/description only,
    # so the judge isn't anchored on the revision step's own severity labels.
    slim_gaps = [
        {"id": g["id"], "requirement": g.get("requirement", ""), "gap": g.get("description", "")}
        for g in gaps
    ]
    user_prompt = prompts.JUDGE_USER_TEMPLATE.format(
        gaps_json=json.dumps(slim_gaps, indent=2),
        revised_policy=revised_policy_text,
    )
    raw = ollama_client.chat(user_prompt, system=prompts.JUDGE_SYSTEM, json_mode=True, temperature=0.1)
    parsed = _parse_judge_json(raw)

    verdicts = parsed.get("verdicts", [])
    addressed_count = sum(1 for v in verdicts if v.get("addressed") is True)
    return {
        "verdicts": verdicts,
        "overall_score": parsed.get("overall_score"),
        "addressed_count": addressed_count,
        "total": len(gaps),
        "_parse_error": parsed.get("_parse_error", False),
    }
