from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_s0_fixtures.py"


class S0FixtureTests(unittest.TestCase):
    def run_validator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_contract_and_golden_outcomes_validate(self) -> None:
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validation passed", result.stdout)

    def test_materialised_seed_is_repeatable(self) -> None:
        first = self.run_validator("--render-seed")
        second = self.run_validator("--render-seed")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn('"seed_id": "synthetic_centre_v1"', first.stdout)


if __name__ == "__main__":
    unittest.main()
