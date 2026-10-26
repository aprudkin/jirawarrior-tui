#!/usr/bin/env python3
"""Preflight and recover this project's uv tool from exact Git commit IDs."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = "https://github.com/aprudkin/jirawarrior-tui.git"
PACKAGE = "jirawarrior-tui"
COMMANDS = ("jirawarrior", "jw")
SHA = re.compile(r"^[0-9a-f]{40}$")


class UpdateError(RuntimeError):
    pass


def run(args, *, env=None, cwd=None, check=True):
    try:
        result = subprocess.run(
            args, check=False, cwd=cwd, env=env, text=True, capture_output=True
        )
    except OSError as error:
        raise UpdateError(f"could not launch {args[0]}: {error.strerror}") from error
    if check and result.returncode:
        raise UpdateError(f"command failed ({result.returncode}): {args[0]} {args[1]}")
    return result


def origin(tool_dir):
    envs = (tool_dir / PACKAGE,)
    for env_dir in envs:
        for metadata in env_dir.glob(
            "lib/python*/site-packages/*.dist-info/direct_url.json"
        ):
            try:
                data = json.loads(metadata.read_text())
                vcs = data.get("vcs_info", {})
                if (
                    data.get("url") == REPOSITORY
                    and vcs.get("vcs") == "git"
                    and SHA.fullmatch(vcs.get("commit_id", ""))
                ):
                    return vcs["commit_id"]
            except (OSError, ValueError):
                continue
    return None


def check_commands(bin_dir):
    with tempfile.TemporaryDirectory(prefix="jirawarrior-cli-check-") as temporary:
        config = Path(temporary) / "config.toml"
        config.write_text(
            'url = "https://jira.example.invalid/jira"\n'
            'token_env = "JW_UPDATE_SYNTHETIC_MISSING_TOKEN"\n'
        )
        env = os.environ.copy()
        env.pop("JW_UPDATE_SYNTHETIC_MISSING_TOKEN", None)
        for command in COMMANDS:
            executable = bin_dir / command
            if not executable.is_file():
                raise UpdateError(f"missing installed command: {command}")
            result = run([str(executable), "--help"], cwd=temporary, check=False)
            if result.returncode or f"usage: {command} " not in result.stdout:
                raise UpdateError(f"installed command failed --help: {command}")
            regression = run(
                [str(executable), "--check", "--config", str(config)],
                cwd=temporary,
                env=env,
                check=False,
            )
            if (
                regression.returncode != 1
                or "Переменная окружения с токеном" not in regression.stderr
            ):
                raise UpdateError(
                    f"installed synthetic --check regression failed: {command}"
                )


def main(argv):
    if len(argv) != 2 or not all(SHA.fullmatch(value) for value in argv):
        print(
            "usage: update_uv_tool.py TARGET_SHA PREVIOUS_SHA (both full 40-character Git SHAs)",
            file=sys.stderr,
        )
        return 2
    target_sha, previous_sha = argv
    uv = shutil.which("uv")
    if not uv:
        print("uv is not on PATH", file=sys.stderr)
        return 2
    source = f"git+{REPOSITORY}@"
    try:
        tool_dir = Path(run([uv, "tool", "dir"]).stdout.strip())
        known_origin = origin(tool_dir)
        if known_origin != previous_sha:
            raise UpdateError(
                f"installed provenance is {known_origin or 'unknown'}, not supplied PREVIOUS_SHA; no update attempted"
            )
        check_commands(Path(run([uv, "tool", "dir", "--bin"]).stdout.strip()))
        with tempfile.TemporaryDirectory(prefix="jirawarrior-tool-stage-") as temporary:
            staging = Path(temporary)
            staged_tools = staging / "tools"
            staged_bin = staging / "bin"
            staged_env = os.environ.copy()
            staged_env.update(
                {
                    "UV_TOOL_DIR": str(staged_tools),
                    "UV_TOOL_BIN_DIR": str(staged_bin),
                    "UV_CACHE_DIR": str(staging / "cache"),
                }
            )
            staged_spec = source + target_sha
            run(
                [uv, "tool", "install", "--python", "3.12", staged_spec], env=staged_env
            )
            if origin(staged_tools) != target_sha:
                raise UpdateError("staged tool provenance did not match TARGET_SHA")
            check_commands(staged_bin)

        result = run(
            [
                uv,
                "tool",
                "install",
                "--force",
                "--refresh-package",
                "jirawarrior-tui",
                "--python",
                "3.12",
                source + target_sha,
            ],
            check=False,
        )
        if result.returncode == 0:
            if origin(tool_dir) != target_sha:
                raise UpdateError(
                    "promotion returned success but installed provenance is not TARGET_SHA"
                )
            try:
                check_commands(Path(run([uv, "tool", "dir", "--bin"]).stdout.strip()))
            except UpdateError as validation_error:
                recovery = run(
                    [
                        uv,
                        "tool",
                        "install",
                        "--force",
                        "--no-cache",
                        "--python",
                        "3.12",
                        source + previous_sha,
                    ],
                    check=False,
                )
                recovered = origin(tool_dir)
                if recovery.returncode or recovered != previous_sha:
                    raise UpdateError(
                        f"candidate verification failed; recovery did not confirm PREVIOUS_SHA (observed {recovered or 'unknown'}); inspect before retry"
                    ) from validation_error
                check_commands(Path(run([uv, "tool", "dir", "--bin"]).stdout.strip()))
                raise UpdateError(
                    "candidate verification failed; restored and verified PREVIOUS_SHA"
                ) from validation_error
            print(
                f"Installed and verified {target_sha}; both commands pass --help and synthetic --check."
            )
            return 0

        # A failed process may have changed the environment. Inspect it before any retry.
        observed = origin(tool_dir)
        print(
            f"Promotion exited {result.returncode}; observed installed provenance: {observed or 'unknown'}.",
            file=sys.stderr,
        )
        if observed not in (previous_sha, target_sha):
            raise UpdateError(
                "partial outcome has unknown provenance; refusing to overwrite it"
            )
        if observed == previous_sha:
            try:
                check_commands(Path(run([uv, "tool", "dir", "--bin"]).stdout.strip()))
            except UpdateError as command_error:
                recovery = run(
                    [
                        uv,
                        "tool",
                        "install",
                        "--force",
                        "--no-cache",
                        "--python",
                        "3.12",
                        source + previous_sha,
                    ],
                    check=False,
                )
                recovered = origin(tool_dir)
                if recovery.returncode or recovered != previous_sha:
                    raise UpdateError(
                        f"previous SHA was unusable and recovery did not confirm PREVIOUS_SHA (observed {recovered or 'unknown'}); inspect before retry"
                    ) from command_error
                check_commands(Path(run([uv, "tool", "dir", "--bin"]).stdout.strip()))
                raise UpdateError(
                    "promotion failed; previous command was unusable, restored and verified PREVIOUS_SHA"
                ) from command_error
            raise UpdateError(
                "promotion failed; confirmed the previous exact-SHA installation remains usable"
            )

        recovery = run(
            [
                uv,
                "tool",
                "install",
                "--force",
                "--no-cache",
                "--python",
                "3.12",
                source + previous_sha,
            ],
            check=False,
        )
        recovered = origin(tool_dir)
        if recovery.returncode or recovered != previous_sha:
            raise UpdateError(
                f"recovery did not confirm PREVIOUS_SHA (observed {recovered or 'unknown'}); inspect before retry"
            )
        check_commands(Path(run([uv, "tool", "dir", "--bin"]).stdout.strip()))
        raise UpdateError(
            "promotion failed; recovered and verified the previous exact-SHA installation"
        )
    except (OSError, UpdateError) as error:
        print(f"update not confirmed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
