"""Command receipt public CLI; every repo, command and artifact is synthetic."""
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_attempt.py"


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        for args in [("init", "-q"), ("config", "user.name", "Synthetic"),
                     ("config", "user.email", "synthetic@example.invalid")]:
            subprocess.run(["git", "-C", str(self.repo), *args], check=True)
        (self.repo / "source").write_text("baseline\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "baseline"], check=True)

    def call(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo), *args],
                              capture_output=True, text=True, env=env, timeout=10, check=False)

    def run_check(self, code="print('synthetic output')", *options):
        return self.call("run", "--label", "synthetic", *options, "--", sys.executable, "-c", code)

    def test_concurrent_attempts_keep_distinct_private_outputs_and_reject_reuse(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.run_check(), range(2)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        receipts = [json.loads(result.stdout) for result in results]
        self.assertNotEqual(receipts[0]["attempt"], receipts[1]["attempt"])
        for receipt in receipts:
            self.assertEqual(receipt["outcome"], "PASS")
            directory = Path(receipt["directory"])
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory / "stdout").read_text(), "synthetic output\n")
            original = (directory / "result.json").read_bytes()
            repeated = self.run_check("print('overwrite')", "--attempt", receipt["attempt"])
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual((directory / "result.json").read_bytes(), original)
            self.assertEqual(self.call("verify", receipt["attempt"]).returncode, 0)

    def test_fail_timeout_and_interruption_never_become_pass_on_retry(self):
        failed = self.run_check("raise SystemExit(7)")
        self.assertNotEqual(failed.returncode, 0)
        failure = json.loads(failed.stdout)
        self.assertEqual(failure["outcome"], "FAIL")
        self.assertEqual(failure["exitStatus"], 7)
        timed = self.run_check("import time; time.sleep(10)", "--timeout", "0.1")
        self.assertNotEqual(timed.returncode, 0)
        self.assertEqual(json.loads(timed.stdout)["outcome"], "TIMEOUT")
        killed = self.run_check("import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
        self.assertEqual(json.loads(killed.stdout)["outcome"], "INTERRUPTED")
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(json.loads(self.call("status", failure["attempt"]).stdout)["outcome"], "FAIL")
        self.assertNotEqual(self.call("verify", failure["attempt"]).returncode, 0)

    def test_killed_runner_leaves_started_evidence_with_unknown_outcome(self):
        result = self.run_check("import os, signal; os.kill(os.getppid(), signal.SIGKILL)",
                                "--attempt", "killed-runner")
        self.assertNotEqual(result.returncode, 0)
        status = self.call("status", "killed-runner", "--full")
        evidence = json.loads(status.stdout)
        self.assertEqual(evidence["outcome"], "UNKNOWN")
        self.assertIn("startedAt", evidence)
        self.assertNotIn("endedAt", evidence)
        self.assertNotEqual(self.call("verify", "killed-runner").returncode, 0)
        unknown = self.call("status", "not-a-real-id")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertEqual(unknown.stdout, "")

    def test_dirty_candidate_and_environment_changes_invalidate_success(self):
        source = self.repo / "source"
        source.write_text("dirty candidate\n")
        receipt = json.loads(self.run_check().stdout)
        self.assertEqual(self.call("verify", receipt["attempt"]).returncode, 0)
        source.write_text("different dirty candidate\n")
        self.assertNotEqual(self.call("verify", receipt["attempt"]).returncode, 0)
        source.write_text("dirty candidate\n")
        extra = self.repo / "new-fixture"
        extra.write_text("fixture\n")
        self.assertNotEqual(self.call("verify", receipt["attempt"]).returncode, 0)
        extra.unlink()
        self.assertEqual(self.call("verify", receipt["attempt"]).returncode, 0)
        env = dict(os.environ, SYNTHETIC_ENV_CHANGE="changed")
        self.assertNotEqual(self.call("verify", receipt["attempt"], env=env).returncode, 0)
        mutated = self.run_check("from pathlib import Path; Path('source').write_text('mutated during check')")
        self.assertNotEqual(mutated.returncode, 0)
        self.assertEqual(json.loads(mutated.stdout)["outcome"], "INVALIDATED")

    def test_declared_ignored_dependency_changes_invalidate_receipt(self):
        dependency = Path(self.temp.name) / "synthetic-package.json"
        dependency.write_text('{"version":"1"}')
        result = self.run_check("print('dependency checked')", "--dependency", str(dependency))
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(self.call("verify", receipt["attempt"]).returncode, 0)
        dependency.write_text('{"version":"2"}')
        self.assertNotEqual(self.call("verify", receipt["attempt"]).returncode, 0)

    def test_dependency_symlink_retarget_and_nested_installed_code_invalidate(self):
        root = Path(self.temp.name)
        one, two = root / 'version-one', root / 'version-two'
        one.mkdir()
        two.mkdir()
        (one / 'index.d.ts').write_text('export type Result = string;')
        (two / 'index.d.ts').write_text('export type Result = number;')
        current = root / 'current'
        current.symlink_to(one, target_is_directory=True)
        result = self.run_check("print('dependency checked')", '--dependency', str(current))
        self.assertEqual(result.returncode, 0, result.stderr)
        attempt = json.loads(result.stdout)['attempt']
        self.assertEqual(self.call('verify', attempt).returncode, 0)
        current.unlink()
        current.symlink_to(two, target_is_directory=True)
        self.assertNotEqual(self.call('verify', attempt).returncode, 0)
        current.unlink()
        current.symlink_to(one, target_is_directory=True)
        self.assertEqual(self.call('verify', attempt).returncode, 0)
        (one / 'index.d.ts').write_text('export type Result = never;')
        self.assertNotEqual(self.call('verify', attempt).returncode, 0)


if __name__ == "__main__":
    unittest.main()
