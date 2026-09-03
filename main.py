"""CLI entry point for a single policy run.

Example:
    python main.py --policy data/dummy_policies/patch_management_policy.txt \
        --domain "Patch Management" --outdir output/

One-time setup before your first run:
    python build_reference_data.py    # parses data/reference_guide.pdf -> data/nist_csf_mapping.json

For running all four dummy policies at once with evaluation metrics, use
evaluate.py instead of this script.
"""
import argparse
import sys
from pathlib import Path

import config
import gap_analysis
import policy_revision
from ollama_client import OllamaConnectionError
from pdf_utils import load_policy_text


def main():
    parser = argparse.ArgumentParser(description="Local LLM policy gap analysis & revision")
    parser.add_argument("--policy", required=True, type=Path, help="Path to policy file (.pdf/.docx/.txt)")
    parser.add_argument("--domain", required=True, choices=config.POLICY_DOMAINS,
                         help="Policy domain, used to select relevant NIST CSF requirements")
    parser.add_argument("--outdir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--chat-model", default=config.CHAT_MODEL)
    args = parser.parse_args()

    config.CHAT_MODEL = args.chat_model

    if not args.policy.exists():
        sys.exit(f"Policy file not found: {args.policy}")
    if not config.NIST_MAPPING_JSON.exists():
        sys.exit(
            f"{config.NIST_MAPPING_JSON} not found. Run `python build_reference_data.py` first."
        )

    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"Loading policy: {args.policy}")
    policy_text = load_policy_text(args.policy)

    try:
        print(f"Running gap analysis (Task 1) against domain: {args.domain} ...")
        analysis = gap_analysis.analyze_policy(policy_text, args.domain)
        gap_report = gap_analysis.render_gap_report(analysis)
        (args.outdir / "gap_report.md").write_text(gap_report)
        print(f"  -> {args.outdir / 'gap_report.md'}  "
              f"({len(analysis['gaps'])} gaps / {analysis['requirements_checked']} requirements checked)")

        print(f"Revising policy (Task 2)... this generates a full rewritten document, so it can "
              f"take several minutes on CPU (timeout set to {config.OLLAMA_TIMEOUT_SECONDS}s) -- "
              f"this is normal, not a hang.")
        revised = policy_revision.revise_policy(policy_text, analysis)
        (args.outdir / "revised_policy.md").write_text(revised)
        print(f"  -> {args.outdir / 'revised_policy.md'}")

        print("Generating roadmap...")
        roadmap = policy_revision.generate_roadmap(analysis)
        (args.outdir / "roadmap.md").write_text(roadmap)
        print(f"  -> {args.outdir / 'roadmap.md'}")
    except OllamaConnectionError as e:
        sys.exit(f"ERROR: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
