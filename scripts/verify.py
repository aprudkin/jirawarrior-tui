#!/usr/bin/env python3
"""Run deterministic checks with repository-local immutable command receipts."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from check_attempt import candidate, environment, git, load, run

ROOT = Path(__file__).resolve().parents[1]
FAST_TESTS = ("configuration", "sprint")


def profiles():
    return {path.stem.removeprefix("test_"): path for path in (ROOT / "tests").glob("test_*.py")}


def install_hook():
    existing = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=ROOT,
                              capture_output=True, text=True, check=False)
    if existing.returncode == 0 and existing.stdout.strip() != ".githooks":
        raise ValueError("Existing core.hooksPath differs; refusing to replace foreign hooks")
    default = Path(git(ROOT, "rev-parse", "--git-path", "hooks").decode().strip())
    if not default.is_absolute():
        default = ROOT / default
    if existing.returncode != 0 and default.exists() and any(
        file.is_file() and not file.name.endswith(".sample") for file in default.iterdir()
    ):
        raise ValueError("Existing local hooks; integrate explicitly, do not replace")
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=ROOT, check=True)
    print("Installed repository-local .githooks (shared by its worktrees).")
    return 0


def dependencies():
    paths = [Path(sysconfig.get_path('stdlib')), Path(sysconfig.get_path('purelib'))]
    paths += [file for file in (ROOT / '.venv/pyvenv.cfg', ROOT / 'uv.lock') if file.is_file()]
    paths += [Path(value) for name in ('uv', 'task', 'ps', 'lsof') if (value := shutil.which(name))]
    return sorted({str(file.absolute()) for file in paths})


def full_receipt(attempt):
    directory, receipt = load(ROOT, attempt)
    command = [sys.executable, "-B", str(ROOT / "scripts/verify.py"), "_run", "full"]
    current = candidate(ROOT)
    if not (receipt["outcome"] == "PASS" and receipt["label"] == "full"
            and receipt["command"] == command and receipt["repository"] == str(ROOT)
            and receipt["candidate"] == receipt.get("candidateAfter") == current
            and receipt["environment"] == environment(command, dependencies())):
        raise ValueError("No current full receipt for this exact candidate/environment; rerun full")
    return directory


def pre_push():
    for line in sys.stdin:
        _, local_sha, remote_ref, _ = line.split()
        if remote_ref != "refs/heads/main" or set(local_sha) == {"0"}:
            continue
        if git(ROOT, "rev-parse", "HEAD").decode().strip() != local_sha:
            raise ValueError("Run full in the actual outgoing main candidate checkout")
        if git(ROOT, "status", "--porcelain", "--untracked-files=all").strip():
            raise ValueError("Main publication requires a clean full-checked candidate")
        saved = subprocess.run(["git", "config", "--local", "--get", "checks.fullReceipt"], cwd=ROOT,
                               capture_output=True, text=True, check=False)
        if saved.returncode:
            raise ValueError("Run full before main promotion/push")
        full_receipt(saved.stdout.strip())
    return 0


def execute(profile):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if profile == "full":
        missing = [name for name in ("lsof", "ps", "task") if not shutil.which(name)]
        if sys.platform != "darwin" or missing:
            print("NOT RUN: full requires macOS and lsof, ps, Go Task; missing: " + ", ".join(missing), file=sys.stderr)
            return 2
        selected = [None]
    else:
        selected = FAST_TESTS if profile == "fast" else [profile]
    statuses = []
    for name in selected:
        command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
        if name:
            command += ["-p", f"test_{name}.py"]
        print("CHECK " + json.dumps(command), flush=True)
        statuses.append(subprocess.run(command, cwd=ROOT, env=env, check=False).returncode)
    return int(any(statuses))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fast", "full", "profile", "install-hook", "pre-commit", "pre-push", "verify-full", "_run"))
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    if args.mode == "install-hook":
        if args.name:
            parser.error("install-hook does not accept an ID/profile")
        return install_hook()
    if args.mode == "pre-push":
        if args.name:
            parser.error("pre-push does not accept an ID/profile")
        return pre_push()
    if args.mode == "verify-full":
        if not args.name:
            parser.error('verify-full requires an attempt ID')
        print(full_receipt(args.name))
        return 0
    if args.mode == "_run":
        if args.name not in ("full", "fast", *profiles()):
            parser.error("Unknown internal profile")
        return execute(args.name)
    if args.mode == "profile":
        if not args.name or args.name.removeprefix("test_") not in profiles():
            parser.error("unknown test profile")
        profile = args.name.removeprefix("test_")
    else:
        if args.name:
            parser.error(args.mode + " does not accept an ID/profile")
        profile = args.mode
    if profile == "pre-commit":
        if subprocess.run(["git", "diff", "--quiet", "--", "src", "tests", "scripts", ".githooks", "pyproject.toml", "uv.lock"],
                          cwd=ROOT, check=False).returncode:
            raise ValueError("Unstaged check inputs: stage intended code before committing")
        subprocess.run(["git", "diff", "--cached", "--check"], cwd=ROOT, check=True)
        profile = "fast"
    result = run(ROOT, [sys.executable, "-B", str(ROOT / "scripts/verify.py"), "_run", profile],
                 profile, timeout=1800 if profile == "full" else 600, dependencies=dependencies())
    print(json.dumps(result))
    if result["outcome"] == "PASS" and profile == "full":
        subprocess.run(["git", "config", "--local", "checks.fullReceipt", result["attempt"]], cwd=ROOT, check=True)
    return 0 if result["outcome"] == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
