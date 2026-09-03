"""Unit tests for the pipeline, run against a stubbed Ollama client so they
work without a live Ollama server. This is what should give you (and judges)
confidence the plumbing is correct independent of any particular model's
output quality.

Run with:
    python -m unittest discover -s tests -v
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import gap_analysis
import policy_revision
import reference_data
from pdf_utils import load_policy_text, split_policy_into_sections


class TestReferenceData(unittest.TestCase):
    def test_mapping_loads_and_has_entries(self):
        mapping = reference_data.load_mapping()
        self.assertGreater(len(mapping), 0)
        for entry in mapping[:5]:
            self.assertIn("id", entry)
            self.assertIn("description", entry)
            self.assertIn("policies", entry)

    def test_every_domain_resolves_to_requirements(self):
        for domain in config.POLICY_DOMAINS:
            reqs = reference_data.get_domain_requirements(domain)
            self.assertGreater(len(reqs), 0, f"{domain} resolved to zero requirements")
            for r in reqs:
                self.assertTrue(set(r["matched_policies"]) & set(config.DOMAIN_POLICY_MAP[domain]))

    def test_unknown_domain_raises(self):
        with self.assertRaises(ValueError):
            reference_data.get_domain_requirements("Not A Real Domain")


class TestPdfUtils(unittest.TestCase):
    def test_load_txt_policy(self):
        path = config.BASE_DIR / "data" / "dummy_policies" / "isms_policy.txt"
        text = load_policy_text(path)
        self.assertIn("ISMS", text.upper())

    def test_split_into_sections_finds_headings(self):
        text = "1. Purpose\nSome text.\n\n2. Scope\nMore text."
        sections = split_policy_into_sections(text)
        self.assertGreaterEqual(len(sections), 2)


def _make_fake_chat(results_status="not_covered"):
    """Builds a fake ollama_client.chat that returns deterministic, valid JSON
    for whatever batch of requirement ids it's asked about."""
    import re

    def fake_chat(prompt, system=None, json_mode=False, model=None, temperature=0.2):
        if system and "auditor" in system.lower():
            ids = re.findall(r'"id":\s*"([^"]+)"', prompt)
            results = [
                {"id": i, "status": results_status,
                 "severity": None if results_status == "covered" else "high",
                 "description": f"stub assessment for {i}", "policy_reference": "none"}
                for i in ids
            ]
            return json.dumps({"results": results})
        if system and "policy writer" in system.lower():
            return "# Revised Policy\n\nStub revised content."
        if system and "roadmap" in system.lower():
            return "# Roadmap\n\n| Function | ID | Priority | Action | Timeframe |\n|---|---|---|---|---|"
        if system and "reviewer" in system.lower():
            ids = re.findall(r'"id":\s*"([^"]+)"', prompt)
            verdicts = [{"id": i, "addressed": True, "note": "stub"} for i in ids]
            return json.dumps({"verdicts": verdicts, "overall_score": 4})
        return "{}"

    return fake_chat


class TestGapAnalysisWithStubbedLLM(unittest.TestCase):
    def test_all_requirements_get_a_verdict(self):
        with patch("ollama_client.chat", _make_fake_chat("not_covered")):
            analysis = gap_analysis.analyze_policy("dummy policy text", "Patch Management")
        total = len(analysis["gaps"]) + len(analysis["adequate"])
        self.assertEqual(total, analysis["requirements_checked"])
        self.assertEqual(analysis["unverified_count"], 0)

    def test_covered_status_routes_to_adequate(self):
        with patch("ollama_client.chat", _make_fake_chat("covered")):
            analysis = gap_analysis.analyze_policy("dummy policy text", "Risk Management")
        self.assertEqual(len(analysis["gaps"]), 0)
        self.assertEqual(len(analysis["adequate"]), analysis["requirements_checked"])

    def test_requirement_text_survives_merge(self):
        """Regression test for the description/requirement key-collision bug:
        the original NIST requirement text must not be overwritten by the
        LLM's gap description."""
        with patch("ollama_client.chat", _make_fake_chat("not_covered")):
            analysis = gap_analysis.analyze_policy("dummy policy text", "Risk Management")
        gap = analysis["gaps"][0]
        self.assertNotEqual(gap["requirement"], gap["description"])
        self.assertTrue(len(gap["requirement"]) > 0)

    def test_missing_verdict_falls_back_gracefully(self):
        def flaky_chat(prompt, system=None, json_mode=False, model=None, temperature=0.2):
            if system and "auditor" in system.lower():
                return json.dumps({"results": []})  # simulate a model that returns nothing
            return "{}"

        with patch("ollama_client.chat", flaky_chat):
            analysis = gap_analysis.analyze_policy("dummy policy text", "Patch Management")
        self.assertEqual(analysis["unverified_count"], analysis["requirements_checked"])
        for g in analysis["gaps"]:
            self.assertTrue(g.get("_verdict_missing"))

    def test_render_gap_report_runs_without_error(self):
        with patch("ollama_client.chat", _make_fake_chat("not_covered")):
            analysis = gap_analysis.analyze_policy("dummy policy text", "Data Privacy and Security")
        report = gap_analysis.render_gap_report(analysis)
        self.assertIn("# Policy Gap Analysis Report", report)
        self.assertIn("Data Privacy and Security", report)


class TestPolicyRevisionWithStubbedLLM(unittest.TestCase):
    def test_revise_and_roadmap_and_judge(self):
        with patch("ollama_client.chat", _make_fake_chat("not_covered")):
            analysis = gap_analysis.analyze_policy("dummy policy text", "Patch Management")
            revised = policy_revision.revise_policy("original text", analysis)
            roadmap = policy_revision.generate_roadmap(analysis)
            judgment = policy_revision.judge_revision(revised, analysis)

        self.assertIn("Revised Policy", revised)
        self.assertIn("Roadmap", roadmap)
        self.assertEqual(judgment["total"], len(analysis["gaps"]))
        self.assertEqual(judgment["addressed_count"], len(analysis["gaps"]))

    def test_no_gaps_short_circuits_revision(self):
        with patch("ollama_client.chat", _make_fake_chat("covered")):
            analysis = gap_analysis.analyze_policy("dummy policy text", "Patch Management")
        revised = policy_revision.revise_policy("ORIGINAL TEXT HERE", analysis)
        self.assertIn("ORIGINAL TEXT HERE", revised)  # unchanged, not re-generated


if __name__ == "__main__":
    unittest.main()
