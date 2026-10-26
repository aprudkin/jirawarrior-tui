#!/usr/bin/env python3
"""Private, repository-local command receipts. No journal, scheduler or automatic retry."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


# Reused verbatim from instruction_patches.atomic_create. Kept standalone so the
# same runner can be vendored by Jira without installing Pi or its patch engine.
def atomic_create(path, data, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        os.fchmod(stream.fileno(), mode)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n").encode()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE,
                                   env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})


def candidate(repo):
    names = set(git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")) - {b""}
    files = {}
    for raw in sorted(names):
        name = os.fsdecode(raw)
        path = repo / name
        if path.is_symlink():
            value = ["symlink", os.readlink(path)]
        elif path.is_file():
            value = ["file", bool(path.stat().st_mode & 0o111), sha(path.read_bytes())]
        elif not path.exists():
            value = ["deleted"]
        else:
            raise ValueError("Unsupported candidate entry (including submodule): " + name)
        files[name] = value
    try:
        head = git(repo, "rev-parse", "--verify", "HEAD").decode().strip()
    except subprocess.CalledProcessError:
        head = None
    return {"head": head, "filesSha256": sha(encoded(files)),
            "indexSha256": sha(git(repo, "ls-files", "--stage", "-z")),
            "diffSha256": sha(git(repo, "diff", "--binary", "--no-ext-diff", *( ["HEAD"] if head else [] ))),
            "fileCount": len(files)}


def input_digest(path, ancestors=frozenset()):
    """Hash only explicitly declared files/trees, retaining symlink routing identity."""
    resolved = path.resolve()
    if resolved in ancestors:
        raise ValueError("Dependency symlink cycle")
    if path.is_dir():
        values = {item.name: input_digest(item, ancestors | {resolved})
                  for item in sorted(path.iterdir())
                  if item.name != "__pycache__" and item.suffix != ".pyc"}
        content = sha(encoded(values))
    elif path.is_file():
        content = sha(path.read_bytes())
    else:
        raise ValueError("Missing/unsupported dependency: " + str(path))
    return {"resolved": str(resolved), "sha256": content,
            "executable": bool(path.stat().st_mode & 0o111)}


def environment(command, dependencies=()):
    # Values are hashed, never copied to receipts. Shell bookkeeping is not a dependency.
    env = {key: value for key, value in os.environ.items()
           if key not in {"_", "PWD", "OLDPWD", "SHLVL"} and not key.startswith("GIT_")}
    executable = shutil.which(command[0])
    inputs = {str(Path(file).absolute()): input_digest(Path(file)) for file in dependencies}
    return {"variablesSha256": sha(encoded(env)), "platform": platform.platform(),
            "dependencies": inputs, "executable": executable,
            "executableSha256": sha(Path(executable).read_bytes()) if executable else None,
            "python": sys.version, "runnerSha256": sha(Path(__file__).read_bytes())}


def store(repo):
    common = Path(os.fsdecode(git(repo, "rev-parse", "--git-common-dir")).strip())
    if not common.is_absolute():
        common = repo / common
    root = common.resolve() / "check-attempts"
    if root.is_symlink():
        raise ValueError("Unsafe receipt directory")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.geteuid() or not root.is_dir():
        raise ValueError("Unsafe receipt owner")
    os.chmod(root, 0o700)
    return root


def attempt_path(repo, attempt):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", attempt):
        raise ValueError("Invalid attempt ID")
    path = store(repo) / attempt
    if path.is_symlink():
        raise ValueError("Unsafe attempt directory")
    return path


def now():
    return datetime.now(UTC).isoformat()


def run(repo, command, label, timeout=600, attempt=None, dependencies=()):
    if not command or timeout <= 0:
        raise ValueError("Command and positive timeout required")
    attempt = attempt or str(uuid.uuid4())
    directory = attempt_path(repo, attempt)
    directory.mkdir(mode=0o700)  # Collision/retry never opens an existing attempt.
    before = candidate(repo)
    start = {"version": 1, "attempt": attempt, "repository": str(repo), "command": command,
             "label": label, "startedAt": now(), "outcome": "STARTED", "pid": os.getpid(),
             "timeoutSeconds": timeout, "candidate": before, "environment": environment(command, dependencies),
             "stdout": str(directory / "stdout"), "stderr": str(directory / "stderr")}
    atomic_create(directory / "start.json", encoded(start), 0o600)
    began = time.monotonic()
    code, process, detail = None, None, None
    def interrupted(signum, frame):
        raise InterruptedError("Runner received signal " + str(signum))
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with (directory / "stdout").open("xb") as out, (directory / "stderr").open("xb") as err:
            os.chmod(out.name, 0o600)
            os.chmod(err.name, 0o600)
            process = subprocess.Popen(command, cwd=repo, stdout=out, stderr=err, start_new_session=True)
            code = process.wait(timeout=timeout)
            outcome = "PASS" if code == 0 else "INTERRUPTED" if code < 0 else "FAIL"
    except subprocess.TimeoutExpired:
        outcome = "TIMEOUT"
    except (InterruptedError, KeyboardInterrupt):
        outcome = "INTERRUPTED"
    except OSError as error:
        outcome, detail = "ERROR", type(error).__name__
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if process:
            # Also stop descendants retaining output descriptors after their leader exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            code = process.returncode
    after = candidate(repo)
    if outcome == "PASS" and (before != after or start["environment"] != environment(command, dependencies)):
        outcome = "INVALIDATED"
    output = ''.join((directory / name).read_text(errors='replace') for name in ('stdout', 'stderr'))
    counts = re.findall(r'(?:skipped=|# skipped )(\d+)', output)
    reported_skips = sum(map(int, counts)) if counts else (
        0 if re.search(r'Ran \d+ tests?|# tests \d+', output) else None)
    result = {**start, "endedAt": now(), "durationSeconds": time.monotonic() - began,
              "exitStatus": code, "outcome": outcome, "candidateAfter": after, "error": detail,
              "reportedSkips": reported_skips, "skipSource": "unittest/Node summaries, null if not reported"}
    atomic_create(directory / "result.json", encoded(result), 0o600)
    return {"attempt": attempt, "directory": str(directory), "outcome": outcome,
            "exitStatus": code, "durationSeconds": result["durationSeconds"], "reportedSkips": reported_skips}


def load(repo, attempt):
    directory = attempt_path(repo, attempt)
    try:
        start = json.loads((directory / "start.json").read_text())
        result = directory / "result.json"
        return directory, json.loads(result.read_text()) if result.exists() else {**start, "outcome": "UNKNOWN"}
    except (OSError, ValueError) as error:
        raise ValueError("Unknown or unreadable attempt receipt; no global fallback") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="action", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--label", required=True)
    execute.add_argument("--attempt")
    execute.add_argument("--dependency", action="append", default=[], help="Explicit environment file/tree to hash (never copy); omit secret/runtime directories")
    execute.add_argument("--timeout", type=float, default=600)
    execute.add_argument("command", nargs=argparse.REMAINDER)
    for name in ("status", "verify"):
        query = commands.add_parser(name)
        query.add_argument("attempt")
        query.add_argument("--label")
        query.add_argument("--full", action="store_true")
    args = parser.parse_args()
    repo = Path(os.fsdecode(git(args.repo, "rev-parse", "--show-toplevel")).strip()).resolve()
    if args.action == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        summary = run(repo, command, args.label, args.timeout, args.attempt, args.dependency)
        print(json.dumps(summary))
        return 0 if summary["outcome"] == "PASS" else 1
    directory, result = load(repo, args.attempt)
    current = (result["outcome"] == "PASS" and result.get("candidate") == result.get("candidateAfter")
               == candidate(repo) and result["environment"] == environment(result["command"], result["environment"]["dependencies"])
               and result["repository"] == str(repo))
    if args.label and result["label"] != args.label:
        current = False
    print(json.dumps(result if args.full else {"attempt": args.attempt, "outcome": result["outcome"],
                                              "current": current, "directory": str(directory)}))
    return 0 if args.action == "status" or current else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
