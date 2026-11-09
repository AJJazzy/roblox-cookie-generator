import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from session_fixtures import MAX_CASES, OUTCOMES, generate_fixtures, verify_fixtures


ROOT = Path(__file__).resolve().parents[1]


class FixtureTests(unittest.TestCase):
    def test_seed_reproduces_batch_and_covers_all_outcomes(self):
        fixtures = generate_fixtures(12, seed=42)
        self.assertEqual(fixtures, generate_fixtures(12, seed=42))
        self.assertNotEqual(fixtures, generate_fixtures(12, seed=43))
        self.assertEqual([case["expected"] for case in fixtures["cases"]], list(OUTCOMES) * 2)
        self.assertEqual(verify_fixtures(fixtures), (12, []))

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
        fixtures = generate_fixtures(3, seed=42)
        active, expired, revoked = [case["cookie"] for case in fixtures["cases"]]
        fixtures["sessions"][active]["expires_at"] = fixtures["reference_time"] + 1
        fixtures["sessions"][expired]["expires_at"] = fixtures["reference_time"]
        fixtures["sessions"][revoked]["expires_at"] = fixtures["reference_time"] - 1
        self.assertEqual(verify_fixtures(fixtures), (3, []))

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
            ("version", 2),
            ("reference_time", False),
            ("sessions", []),
            ("sessions", {"arbitrary-input": {"expires_at": 0, "revoked": False}}),
            ("cases", []),
            ("cases", [{"expected": "missing"}]),
            ("cases", [{"cookie": None, "expected": ["missing"]}]),
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
        self.assertEqual(len(json.loads(generated.stdout)["cases"]), 18)

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
