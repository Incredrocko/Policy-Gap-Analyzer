"""Evaluation harness: runs the full pipeline (Task 1 + Task 2) against all
four dummy policies in data/dummy_policies/, then judges each revision with
an independent LLM-as-judge pass. Writes per-domain outputs plus a single
aggregate summary.

This is what satisfies "the output of the gap analysis and policy revision
process will be evaluated against them [the dummy policies]" from the
problem statement.

Usage:
    python evaluate.py                  # full run, all 4 domains
    python evaluate.py --skip-judge      # skip the judge pass (faster, 2x fewer LLM calls)
    python evaluate.py --domain "Patch Management"   # just one domain
"""
import argparse
import time
from pathlib import Path

import config
import gap_analysis
import policy_revision
from ollama_client import OllamaConnectionError
from pdf_utils import load_policy_text

DUMMY_POLICY_MANIFEST = {
    "Information Security Management System (ISMS)": "data/dummy_policies/isms_policy.txt",
    "Data Privacy and Security": "data/dummy_policies/data_privacy_policy.txt",
    "Patch Management": "data/dummy_policies/patch_management_policy.txt",
    "Risk Management": "data/dummy_policies/risk_management_policy.txt",
}


def _slug(domain: str) -> str:
    return domain.lower().split(" (")[0].replace(" ", "_")


def evaluate_domain(domain: str, policy_path: Path, outdir: Path, run_judge: bool) -> dict:
    print(f"\n=== {domain} ===")
    policy_text = load_policy_text(policy_path)

    t0 = time.time()
    analysis = gap_analysis.analyze_policy(policy_text, domain)
    t1 = time.time()
    print(f"  Gap analysis: {len(analysis['gaps'])} gaps / {analysis['requirements_checked']} "
          f"requirements checked ({t1 - t0:.1f}s)")

    print("  Revising policy (this can take several minutes on CPU)...")
    revised = policy_revision.revise_policy(policy_text, analysis)
    t2 = time.time()
    print(f"  Revision generated ({t2 - t1:.1f}s)")

    roadmap = policy_revision.generate_roadmap(analysis)

    domain_dir = outdir / _slug(domain)
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "gap_report.md").write_text(gap_analysis.render_gap_report(analysis))
    (domain_dir / "revised_policy.md").write_text(revised)
    (domain_dir / "roadmap.md").write_text(roadmap)

    result = {
        "domain": domain,
        "requirements_checked": analysis["requirements_checked"],
        "gap_count": len(analysis["gaps"]),
        "adequate_count": len(analysis["adequate"]),
        "unverified_count": analysis["unverified_count"],
        "coverage_before_pct": round(100 * len(analysis["adequate"]) / analysis["requirements_checked"], 1),
    }

    if run_judge:
        judgment = policy_revision.judge_revision(revised, analysis)
        t3 = time.time()
        print(f"  Judge pass: {judgment['addressed_count']}/{judgment['total']} gaps "
              f"addressed, score {judgment['overall_score']}/5 ({t3 - t2:.1f}s)")
        result.update({
            "judge_score": judgment["overall_score"],
            "judge_addressed": judgment["addressed_count"],
            "judge_total": judgment["total"],
            "coverage_after_pct": (
                round(100 * (len(analysis["adequate"]) + judgment["addressed_count"])
                      / analysis["requirements_checked"], 1)
                if analysis["requirements_checked"] else None
            ),
        })
        (domain_dir / "judge_verdicts.md").write_text(
            "# Judge Verdicts\n\n" + "\n".join(
                f"- **{v.get('id')}**: {'✅ addressed' if v.get('addressed') else '❌ not addressed'} "
                f"— {v.get('note', '')}"
                for v in judgment["verdicts"]
            )
        )

    return result


def render_summary(results: list[dict], run_judge: bool) -> str:
    lines = ["# Evaluation Summary\n"]
    header = "| Domain | Requirements | Gaps Found | Adequate (before) | Coverage Before |"
    sep = "|---|---|---|---|---|"
    if run_judge:
        header += " Gaps Addressed by Revision | Coverage After | Judge Score |"
        sep += "---|---|---|"
    lines += [header, sep]

    for r in results:
        row = (f"| {r['domain']} | {r['requirements_checked']} | {r['gap_count']} | "
               f"{r['adequate_count']} | {r['coverage_before_pct']}% |")
        if run_judge:
            row += (f" {r.get('judge_addressed', '-')}/{r.get('judge_total', '-')} | "
                     f"{r.get('coverage_after_pct', '-')}% | {r.get('judge_score', '-')}/5 |")
        lines.append(row)

    if any(r.get("unverified_count") for r in results):
        lines.append("\n⚠ Some requirements had no LLM verdict after retries (counted as "
                      "gaps, flagged per-domain in that domain's gap_report.md):")
        for r in results:
            if r.get("unverified_count"):
                lines.append(f"- {r['domain']}: {r['unverified_count']} unverified")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate the pipeline against the dummy policies")
    parser.add_argument("--domain", choices=list(DUMMY_POLICY_MANIFEST.keys()),
                         help="Evaluate a single domain instead of all four")
    parser.add_argument("--skip-judge", action="store_true",
                         help="Skip the LLM-as-judge pass (faster, no revision-quality scoring)")
    parser.add_argument("--outdir", type=Path, default=config.OUTPUT_DIR / "evaluation")
    args = parser.parse_args()

    domains = [args.domain] if args.domain else list(DUMMY_POLICY_MANIFEST.keys())
    args.outdir.mkdir(parents=True, exist_ok=True)

    results = []
    try:
        for domain in domains:
            policy_path = config.BASE_DIR / DUMMY_POLICY_MANIFEST[domain]
            results.append(evaluate_domain(domain, policy_path, args.outdir, not args.skip_judge))
    except OllamaConnectionError as e:
        print(f"\nERROR: {e}")
        return

    summary = render_summary(results, not args.skip_judge)
    (args.outdir / "evaluation_summary.md").write_text(summary)
    print(f"\n{summary}\n\nFull results in {args.outdir}/")


if __name__ == "__main__":
    main()
