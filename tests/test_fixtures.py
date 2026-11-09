import json
import subprocess
import sys
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

from session_fixtures import MAX_CASES, OUTCOMES, check_cookie, generate_fixtures, verify_fixtures


ROOT = Path(__file__).resolve().parents[1]


class FixtureTests(unittest.TestCase):
    def test_seed_reproduces_batch_and_covers_all_outcomes(self):
        fixtures = generate_fixtures(12, seed=42, all_outcomes=True)
        self.assertEqual(fixtures, generate_fixtures(12, seed=42, all_outcomes=True))
        self.assertNotEqual(fixtures, generate_fixtures(12, seed=43, all_outcomes=True))
        self.assertEqual([case["expected"] for case in fixtures["cases"]], list(OUTCOMES) * 2)
        self.assertEqual(verify_fixtures(fixtures), (12, []))

        active = generate_fixtures(2, seed=42)
        self.assertEqual(
            active["cases"], [case for case in fixtures["cases"] if case["expected"] == "active"]
        )

    def test_count_bounds(self):
        for count in (1, MAX_CASES):
            with self.subTest(count=count):
                fixtures = generate_fixtures(count, seed=42)
                self.assertEqual(verify_fixtures(fixtures), (count, []))

        for count in (0, -1, MAX_CASES + 1):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, "Count must be"):
                    generate_fixtures(count)

    def test_expiry_boundary_and_revocation_priority(self):
        fixtures = generate_fixtures(3, seed=42, all_outcomes=True)
        active, expired, revoked = [case["cookie"] for case in fixtures["cases"]]
        fixtures["sessions"][active]["expires_at"] = fixtures["reference_time"] + 1
        fixtures["sessions"][expired]["expires_at"] = fixtures["reference_time"]
        fixtures["sessions"][revoked]["expires_at"] = fixtures["reference_time"] - 1
        self.assertEqual(verify_fixtures(fixtures), (3, []))

    def test_cookie_headers_parse_and_only_active_session_resolves_an_account(self):
        fixtures = generate_fixtures(6, seed=42, all_outcomes=True)
        for case in fixtures["cases"]:
            with self.subTest(outcome=case["expected"]):
                header = case["cookie_header"]
                if header is not None:
                    parsed = SimpleCookie(header)
                    self.assertEqual(list(parsed), ["fixture_session"])
                    self.assertEqual(parsed["fixture_session"].value, case["cookie"])

                account = "fixture_account_00001" if case["expected"] == "active" else None
                self.assertEqual(case["expected_account_id"], account)
                self.assertEqual(check_cookie(fixtures, header), (case["expected"], account))

    def test_check_rejects_non_fixture_headers(self):
        fixtures = generate_fixtures(1, seed=42)
        header = fixtures["cases"][0]["cookie_header"]
        for invalid in (
            fixtures["cases"][0]["cookie"],
            "other_session=fixture_invalid",
            f"{header}; other=value",
            f"{header}\r\nX-Test: value",
        ):
            with self.subTest(header=invalid):
                with self.assertRaisesRegex(ValueError, "Cookie header must be one"):
                    check_cookie(fixtures, invalid)

    def test_verify_detects_account_mismatch(self):
        fixtures = generate_fixtures(1, seed=42)
        session = next(iter(fixtures["sessions"].values()))
        session["account_id"] = "fixture_account_99999"
        total, mismatches = verify_fixtures(fixtures)
        self.assertEqual(total, 1)
        self.assertEqual(
            mismatches,
            ["Case 1 expected account 'fixture_account_00001' and got 'fixture_account_99999'."],
        )

    def test_verify_rejects_header_that_does_not_match_cookie(self):
        fixtures = generate_fixtures(2, seed=42)
        fixtures["cases"][0]["cookie_header"] = fixtures["cases"][1]["cookie_header"]
        with self.assertRaisesRegex(ValueError, "requires a cookie_header matching"):
            verify_fixtures(fixtures)

    def test_version_one_fixtures_still_verify(self):
        cookie = "fixture_" + "0" * 32
        fixtures = {
            "version": 1,
            "reference_time": 1,
            "sessions": {cookie: {"expires_at": 2, "revoked": False}},
            "cases": [{"cookie": cookie, "expected": "active"}],
        }
        self.assertEqual(verify_fixtures(fixtures), (1, []))
        self.assertEqual(check_cookie(fixtures, f"fixture_session={cookie}"), ("active", None))

    def test_reports_mismatch_without_echoing_cookie(self):
        fixtures = generate_fixtures(1, seed=42)
        fixtures["cases"][0]["expected"] = "revoked"
        self.assertEqual(
            verify_fixtures(fixtures), (1, ["Case 1 expected revoked and got active."])
        )

    def test_rejects_cookie_outside_fixture_format(self):
        fixtures = generate_fixtures(1, seed=42)
        fixtures["cases"][0]["cookie"] = "arbitrary-input"
        with self.assertRaisesRegex(ValueError, "requires a synthetic cookie"):
            verify_fixtures(fixtures)

    def test_rejects_invalid_fixture_structure(self):
        for field, value in (
            ("version", True),
            ("version", 3),
            ("reference_time", False),
            ("sessions", []),
            ("sessions", {"arbitrary-input": {"expires_at": 0, "revoked": False}}),
            ("cases", []),
            ("cases", [{"expected": "missing"}]),
            ("cases", [{"cookie": None, "expected": ["missing"]}]),
            ("cases", [{"cookie": None, "expected": "missing", "cookie_header": None}]),
        ):
            with self.subTest(field=field, value=value):
                fixtures = generate_fixtures(1, seed=42)
                fixtures[field] = value
                with self.assertRaises(ValueError):
                    verify_fixtures(fixtures)

        fixtures = generate_fixtures(1, seed=42)
        session = next(iter(fixtures["sessions"].values()))
        session["revoked"] = 0
        with self.assertRaisesRegex(ValueError, "Session records"):
            verify_fixtures(fixtures)

        session["revoked"] = False
        session["account_id"] = "arbitrary-account"
        with self.assertRaisesRegex(ValueError, "synthetic account_id"):
            verify_fixtures(fixtures)


class CommandTests(unittest.TestCase):
    def run_cli(self, *arguments, input_text=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "main.py"), *arguments],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_generate_and_verify_from_stdin_and_file(self):
        generated = self.run_cli("generate", "--count", "18", "--seed", "42")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        fixtures = json.loads(generated.stdout)
        self.assertEqual(len(fixtures["cases"]), 18)
        self.assertEqual(len(fixtures["sessions"]), 18)
        self.assertEqual({case["expected"] for case in fixtures["cases"]}, {"active"})

        verified = self.run_cli("verify", input_text=generated.stdout)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(verified.stdout, "Verified 18 fixture cases.\n")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixtures.json"
            path.write_text(generated.stdout, encoding="utf-8")
            verified = self.run_cli("verify", str(path))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(verified.stdout, "Verified 18 fixture cases.\n")

    def test_verify_distinguishes_mismatch_from_invalid_json(self):
        fixtures = generate_fixtures(1, seed=42)
        fixtures["cases"][0]["expected"] = "expired"
        mismatch = self.run_cli("verify", "-", input_text=json.dumps(fixtures))
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("Case 1 expected expired and got active.", mismatch.stderr)
        self.assertEqual(mismatch.stdout, "")

        malformed = self.run_cli("verify", input_text="{")
        self.assertEqual(malformed.returncode, 2)
        self.assertTrue(malformed.stderr)

    def test_check_reports_outcome_and_account_on_the_command_line(self):
        generated = self.run_cli("generate", "--count", "6", "--seed", "42", "--all-outcomes")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        fixture_json = generated.stdout
        fixtures = json.loads(fixture_json)
        self.assertEqual([case["expected"] for case in fixtures["cases"]], list(OUTCOMES))
        for case in (fixtures["cases"][0], fixtures["cases"][3]):
            with self.subTest(outcome=case["expected"]):
                checked = self.run_cli(
                    "check", "-", "--cookie-header", case["cookie_header"], input_text=fixture_json
                )
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertEqual(
                    json.loads(checked.stdout),
                    {"outcome": case["expected"], "account_id": case["expected_account_id"]},
                )

        missing = self.run_cli("check", "-", input_text=fixture_json)
        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertEqual(json.loads(missing.stdout), {"outcome": "missing", "account_id": None})

        invalid = self.run_cli("check", "-", "--cookie-header", "invalid", input_text=fixture_json)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("Cookie header must be one", invalid.stderr)

    def test_rejects_invalid_count_and_oversized_input(self):
        bad_count = self.run_cli("generate", "--count", "0")
        self.assertEqual(bad_count.returncode, 2)
        self.assertIn("Count must be", bad_count.stderr)
        self.assertEqual(bad_count.stdout, "")

        oversized = self.run_cli("verify", input_text=" " * (4 * 1024 * 1024 + 1))
        self.assertEqual(oversized.returncode, 2)
        self.assertIn("4 MiB", oversized.stderr)


if __name__ == "__main__":
    unittest.main()
