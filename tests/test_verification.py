"""Public verification boundary on tiny synthetic repos, not recursive real suites."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VerificationEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jw-verification-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("scripts", "tests", ".githooks"):
            (self.root / directory).mkdir()
        for name in ("verify.py", "check_attempt.py"):
            shutil.copy2(ROOT / "scripts" / name, self.root / "scripts" / name)
        for name in ("pre-commit", "pre-push"):
            shutil.copy2(ROOT / ".githooks" / name, self.root / ".githooks" / name)
        (self.root / ".gitignore").write_text("__pycache__/\n.venv/\n")
        for name in ("configuration", "sprint", "profile_control"):
            (self.root / "tests" / f"test_{name}.py").write_text(
                "import unittest\nclass Control(unittest.TestCase):\n def test_control(self): self.assertTrue(True)\n")
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(PYTHONDONTWRITEBYTECODE="1", UV_PYTHON=sys.executable)
        for args in (("init", "-q"), ("config", "user.name", "Synthetic"),
                     ("config", "user.email", "synthetic@example.invalid")):
            self.assertEqual(self.git(*args).returncode, 0)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], env=self.env,
                              capture_output=True, text=True, check=False)

    def run_verify(self, *args):
        return subprocess.run([sys.executable, str(self.root / "scripts/verify.py"), *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True,
                              timeout=30, check=False)

    def test_profile_runs_only_selected_module_and_rejects_unknown(self):
        (self.root / "tests/test_sprint.py").write_text("raise RuntimeError('other profile must not run')\n")
        result = self.run_verify("profile", "profile_control")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["outcome"], "PASS")
        unknown = self.run_verify("profile", "unknown")
        self.assertEqual(unknown.returncode, 2)
        self.assertNotIn("RuntimeError", unknown.stderr)

    def test_actual_commit_passes_control_rejects_failure_and_unstaged_mask(self):
        self.assertEqual(self.run_verify("install-hook").returncode, 0)
        self.git("add", ".")
        good = self.git("commit", "-qm", "synthetic control")
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        test = self.root / "tests/test_configuration.py"
        test.write_text(test.read_text().replace("self.assertTrue(True)", "self.fail('intentional error')"))
        self.git("add", ".")
        bad = self.git("commit", "-qm", "must fail")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("FAIL", bad.stdout + bad.stderr)
        test.write_text(test.read_text().replace("self.fail('intentional error')", "self.assertTrue(True)"))
        masked = self.git("commit", "-qm", "must reject unstaged fix")
        self.assertNotEqual(masked.returncode, 0)
        self.assertIn("Unstaged", masked.stdout + masked.stderr)

    def test_install_preserves_foreign_hook_configuration(self):
        self.git("config", "core.hooksPath", "foreign-hooks")
        self.assertNotEqual(self.run_verify("install-hook").returncode, 0)
        self.assertEqual(self.git("config", "--get", "core.hooksPath").stdout.strip(), "foreign-hooks")

    def test_full_requires_current_receipt_and_invalidates_after_change(self):
        self.run_verify("install-hook")
        self.git("add", ".")
        self.assertEqual(self.git("commit", "-qm", "candidate").returncode, 0)
        completed = self.run_verify("full")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        attempt = json.loads(completed.stdout)["attempt"]
        self.assertEqual(self.run_verify("verify-full", attempt).returncode, 0)
        (self.root / "fixture").write_text("unverified")
        self.assertNotEqual(self.run_verify("verify-full", attempt).returncode, 0)


if __name__ == "__main__":
    unittest.main()
