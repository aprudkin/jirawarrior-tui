"""Exact-SHA uv tool update flow; fake uv models mutation outcomes."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "scripts/update_uv_tool.py"
OLD = "1" * 40
NEW = "2" * 40


class ToolUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jw-update-")
        self.root = Path(self.temp.name)
        self.uv_log = self.root / "uv.jsonl"
        self.state = self.root / "state.json"
        self.state.write_text(json.dumps({"sha": OLD, "usable": True}))
        tool = (
            self.root
            / "tool/jirawarrior-tui/lib/python3.12/site-packages/jirawarrior_tui-0.2.0.dist-info"
        )
        tool.mkdir(parents=True)
        (tool / "direct_url.json").write_text(
            json.dumps(
                {
                    "url": "https://github.com/aprudkin/jirawarrior-tui.git",
                    "vcs_info": {"vcs": "git", "commit_id": OLD},
                }
            )
        )
        installed_bin = self.root / "tool/bin"
        installed_bin.mkdir(parents=True)
        for name in ("jirawarrior", "jw"):
            command = installed_bin / name
            command.write_text(
                "#!/usr/bin/env python3\nimport json, os, sys\n"
                "print(json.dumps([os.getcwd(), sys.argv[1:]]), file=open(os.environ['COMMAND_CWDS'], 'a'))\n"
                "if '--check' in sys.argv: print('Переменная окружения с токеном отсутствует', file=sys.stderr); raise SystemExit(1)\n"
                "print('usage: " + name + " [options]')\n"
            )
            command.chmod(0o755)
        uv = self.root / "bin/uv"
        uv.parent.mkdir()
        uv.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["UV_LOG"], "a") as f: f.write(json.dumps(args) + "\\n")
if args[:2] == ["tool", "dir"]:
    if "--bin" in args:
        print(os.environ["UV_TOOL_BIN_DIR"])
    else:
        print(os.environ["UV_TOOL_DIR"])
    raise SystemExit()
if args[:2] == ["tool", "install"]:
    spec = args[-1]
    sha = spec.rsplit("@", 1)[-1]
    if pathlib.Path(os.environ["UV_TOOL_DIR"]) != pathlib.Path(os.environ["STATE"]).parent / "tool":
        # Candidate staging succeeds unless fixture asks to fail preparation.
        if os.environ.get("FAIL_STAGE"):
            raise SystemExit(17)
        target = pathlib.Path(os.environ["UV_TOOL_BIN_DIR"])
        target.mkdir(parents=True, exist_ok=True)
        tools = pathlib.Path(os.environ["UV_TOOL_DIR"])
        metadata = tools / "jirawarrior-tui/lib/python3.12/site-packages/jirawarrior_tui-0.2.0.dist-info"
        metadata.mkdir(parents=True, exist_ok=True)
        (metadata / "direct_url.json").write_text(json.dumps({"url": "https://github.com/aprudkin/jirawarrior-tui.git", "vcs_info": {"vcs": "git", "commit_id": sha}}))
        for name in ("jirawarrior", "jw"):
            p = target / name
            p.write_text("#!/usr/bin/env python3\\nimport json, os, sys\\nprint(json.dumps([os.getcwd(), sys.argv[1:]]), file=open(os.environ['COMMAND_CWDS'], 'a'))\\nif '--check' in sys.argv: print('Переменная окружения с токеном отсутствует', file=sys.stderr); raise SystemExit(1)\\nprint('usage: " + name + " [options]')\\n")
            p.chmod(0o755)
        raise SystemExit()
    state = pathlib.Path(os.environ["STATE"])
    tool_dir = pathlib.Path(os.environ["UV_TOOL_DIR"])
    if "--tool-dir" in args:
        tool_dir = pathlib.Path(args[args.index("--tool-dir") + 1])
    env_dir = tool_dir / "jirawarrior-tui"
    metadata = env_dir / "lib/python3.12/site-packages/jirawarrior_tui-0.2.0.dist-info"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / "direct_url.json").write_text(json.dumps({"url": "https://github.com/aprudkin/jirawarrior-tui.git", "vcs_info": {"vcs": "git", "commit_id": sha}}))
    bindir = tool_dir / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    for name in ("jirawarrior", "jw"):
        p = bindir / name
        if os.environ.get("BAD_TARGET_HELP") and sha != os.environ["OLD_SHA"]:
            p.write_text("#!/usr/bin/env python3\\nprint('broken')\\n")
        else:
            p.write_text("#!/usr/bin/env python3\\nimport json, os, sys\\nprint(json.dumps([os.getcwd(), sys.argv[1:]]), file=open(os.environ['COMMAND_CWDS'], 'a'))\\nif '--check' in sys.argv: print('Переменная окружения с токеном отсутствует', file=sys.stderr); raise SystemExit(1)\\nprint('usage: " + name + " [options]')\\n")
        p.chmod(0o644 if os.environ.get("BAD_TARGET_LAUNCH") and sha != os.environ["OLD_SHA"] else 0o755)
    if os.environ.get("PARTIAL_PROMOTION") and sha != os.environ["OLD_SHA"]:
        state.write_text(json.dumps({"sha": sha, "usable": False}))
        raise SystemExit(23)
    state.write_text(json.dumps({"sha": sha, "usable": True}))
    raise SystemExit()
raise SystemExit(99)
""")
        uv.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": f"{uv.parent}:{self.env['PATH']}",
                "UV_LOG": str(self.uv_log),
                "COMMAND_CWDS": str(self.root / "command-cwds.jsonl"),
                "UV_TOOL_DIR": str(self.root / "tool"),
                "UV_TOOL_BIN_DIR": str(self.root / "tool/bin"),
                "UV_CACHE_DIR": str(self.root / "cache"),
                "STATE": str(self.state),
                "OLD_SHA": OLD,
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_update(self, *args, cwd=None, **extra):
        env = self.env.copy()
        env.update(extra)
        return subprocess.run(
            ["python3", str(UPDATER), *args],
            check=False,
            cwd=cwd or self.root,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_preparation_failure_does_not_touch_existing_tool(self):
        result = self.run_update(NEW, OLD, FAIL_STAGE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(self.state.read_text()), {"sha": OLD, "usable": True}
        )
        for name in ("jirawarrior", "jw"):
            command = self.root / "tool/bin" / name
            self.assertEqual(
                subprocess.run(
                    [str(command), "--help"],
                    check=False,
                    env=self.env,
                    capture_output=True,
                ).returncode,
                0,
            )

    def test_foreign_provenance_is_not_overwritten(self):
        metadata = (
            self.root
            / "tool/jirawarrior-tui/lib/python3.12/site-packages/jirawarrior_tui-0.2.0.dist-info/direct_url.json"
        )
        metadata.write_text(
            json.dumps(
                {
                    "url": "https://attacker.invalid/jirawarrior-tui.git",
                    "vcs_info": {"vcs": "git", "commit_id": OLD},
                }
            )
        )
        result = self.run_update(NEW, OLD)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed provenance is unknown", result.stderr)
        self.assertEqual(
            json.loads(self.state.read_text()), {"sha": OLD, "usable": True}
        )
        invocations = [
            json.loads(line) for line in self.uv_log.read_text().splitlines()
        ]
        self.assertFalse(any(call[:2] == ["tool", "install"] for call in invocations))

    def test_partial_promotion_is_reconciled_then_recovered_from_exact_sha(self):
        result = self.run_update(NEW, OLD, PARTIAL_PROMOTION="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"observed installed provenance: {NEW}", result.stderr)
        self.assertEqual(
            json.loads(self.state.read_text()), {"sha": OLD, "usable": True}
        )
        invocations = [
            json.loads(line) for line in self.uv_log.read_text().splitlines()
        ]
        promoted = next(
            i
            for i, call in enumerate(invocations)
            if call[-1].endswith("@" + NEW) and "--force" in call
        )
        recovery = invocations[promoted + 1 :]
        self.assertTrue(any(call[-1].endswith("@" + OLD) for call in recovery))
        self.assertTrue(any(call[:2] == ["tool", "dir"] for call in invocations))

    def test_cli_invoked_from_checkout_runs_installed_commands_in_check_temp_dir(self):
        result = self.run_update(NEW, OLD, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        invocations = [
            json.loads(line)
            for line in (self.root / "command-cwds.jsonl").read_text().splitlines()
        ]
        self.assertTrue(any(arguments == ["--help"] for _, arguments in invocations))
        self.assertTrue(
            any(arguments[:1] == ["--check"] for _, arguments in invocations)
        )
        self.assertTrue(all(Path(cwd) != ROOT for cwd, _ in invocations))
        self.assertTrue(
            all(
                Path(cwd).name.startswith("jirawarrior-cli-check-")
                for cwd, _ in invocations
            )
        )

    def test_non_executable_promoted_command_recovers_from_previous_sha(self):
        result = self.run_update(NEW, OLD, BAD_TARGET_LAUNCH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("restored and verified PREVIOUS_SHA", result.stderr)
        self.assertEqual(
            json.loads(self.state.read_text()), {"sha": OLD, "usable": True}
        )
        for name in ("jirawarrior", "jw"):
            command = self.root / "tool/bin" / name
            self.assertEqual(
                subprocess.run(
                    [str(command), "--help"],
                    check=False,
                    env=self.env,
                    capture_output=True,
                ).returncode,
                0,
            )

    def test_failed_post_promotion_check_restores_known_previous_sha(self):
        result = self.run_update(NEW, OLD, BAD_TARGET_HELP="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("restored and verified PREVIOUS_SHA", result.stderr)
        self.assertEqual(
            json.loads(self.state.read_text()), {"sha": OLD, "usable": True}
        )

    def test_success_checks_both_staged_commands_then_promotes_exact_sha(self):
        result = self.run_update(NEW, OLD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.state.read_text()), {"sha": NEW, "usable": True}
        )
        invocations = [
            json.loads(line) for line in self.uv_log.read_text().splitlines()
        ]
        self.assertTrue(
            any(
                call[-1].endswith("@" + NEW) and "--force" not in call
                for call in invocations
            )
        )
        self.assertTrue(
            any(
                call[-1].endswith("@" + NEW) and "--force" in call
                for call in invocations
            )
        )


if __name__ == "__main__":
    unittest.main()
