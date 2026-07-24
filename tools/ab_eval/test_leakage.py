#!/usr/bin/env python3
"""test_leakage.py — unit tests for leakage.py (secret/PII leakage detection)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from leakage import (  # noqa: E402
    DEFAULT_PATTERNS,
    leakage_violations,
    load_external_scan,
    scan_patterns,
    scan_terms,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRUB_PY = REPO_ROOT / "skills" / "skill-reflect" / "scripts" / "scrub.py"


class TestScanTerms(unittest.TestCase):
    def test_finds_exact_literal(self):
        found = scan_terms("contact alice@example.com now", ["alice@example.com"])
        self.assertEqual(found, ["alice@example.com"])

    def test_does_not_find_absent_term(self):
        self.assertEqual(scan_terms("clean text", ["secret-token"]), [])

    def test_multiple_terms_all_reported(self):
        text = "token=ghp_abc path=/Users/alice/work"
        found = scan_terms(text, ["ghp_abc", "/Users/alice/work", "not-present"])
        self.assertEqual(found, ["ghp_abc", "/Users/alice/work"])

    def test_empty_text_returns_empty(self):
        self.assertEqual(scan_terms("", ["x"]), [])

    def test_empty_terms_returns_empty(self):
        self.assertEqual(scan_terms("anything", []), [])


class TestScanPatterns(unittest.TestCase):
    def test_email_pattern_hits(self):
        hits = scan_patterns("reach me at bob@example.org please")
        self.assertIn("email", hits)
        self.assertEqual(hits["email"], 1)

    def test_ipv4_pattern_hits(self):
        hits = scan_patterns("host is 10.24.8.12 today")
        self.assertIn("ipv4", hits)

    def test_github_token_pattern_hits(self):
        hits = scan_patterns("token: ghp_" + "A" * 30)
        self.assertIn("github-token", hits)

    def test_clean_text_has_no_hits(self):
        self.assertEqual(scan_patterns("nothing sensitive here at all"), {})

    def test_unix_absolute_path_pattern(self):
        hits = scan_patterns("see /Users/alice/work/report.pdf for details")
        self.assertIn("absolute-path-unix", hits)

    def test_windows_absolute_path_pattern(self):
        hits = scan_patterns(r"see C:\Users\alice\report.pdf for details")
        self.assertIn("absolute-path-windows", hits)

    def test_custom_pattern_set_overrides_default(self):
        custom = {"digits": DEFAULT_PATTERNS["ipv4"]}
        hits = scan_patterns("call 192.168.1.1 now", patterns=custom)
        self.assertEqual(set(hits.keys()), {"digits"})


class TestLeakageViolations(unittest.TestCase):
    def test_no_violations_on_clean_text(self):
        self.assertEqual(leakage_violations("hello world", leakage_terms=["secret"]), [])

    def test_reports_one_violation_per_matched_term(self):
        text = "found ghp_ABC and alice@example.com in the log"
        violations = leakage_violations(text, leakage_terms=["ghp_ABC", "alice@example.com"])
        self.assertEqual(len(violations), 2)
        self.assertTrue(all(v["category"] == "leakage" for v in violations))

    def test_absent_term_produces_no_violation(self):
        violations = leakage_violations("clean response", leakage_terms=["ghp_never_here"])
        self.assertEqual(violations, [])


@unittest.skipUnless(SCRUB_PY.exists(), "skill-reflect scrub.py not present in this checkout")
class TestExternalScanIntegration(unittest.TestCase):
    """Reuses skill-reflect's own deterministic scrubber as the external secret scan."""

    def setUp(self):
        self.scrub_text = load_external_scan(SCRUB_PY)

    def test_external_scan_flags_a_github_token(self):
        token = "ghp_" + "B" * 36
        _, findings = self.scrub_text(f"leaked token {token} in output")
        categories = {f["category"] for f in findings}
        self.assertIn("github-token", categories)

    def test_leakage_violations_uses_external_scan_for_secret_categories(self):
        token = "ghp_" + "C" * 36
        violations = leakage_violations(
            f"oops {token} leaked",
            leakage_terms=[],
            external_scan=self.scrub_text,
            external_secret_categories={"github-token", "bearer-token", "aws-access-key"},
        )
        self.assertTrue(any(v.get("external_category") == "github-token" for v in violations))

    def test_external_scan_never_leaks_the_matched_value(self):
        token = "ghp_" + "D" * 36
        violations = leakage_violations(
            f"oops {token} leaked",
            external_scan=self.scrub_text,
            external_secret_categories={"github-token"},
        )
        dumped = repr(violations)
        self.assertNotIn(token, dumped)

    def test_external_scan_category_filter_excludes_unlisted_categories(self):
        # An email is PII but not in scrub.py's SECRET_CATEGORIES; filtering to
        # secret-only categories should not surface it as a "leakage" hit here
        # (exact-term matching remains the correct tool for PII literals).
        violations = leakage_violations(
            "contact alice@example.com",
            external_scan=self.scrub_text,
            external_secret_categories={"github-token", "aws-access-key"},
        )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
