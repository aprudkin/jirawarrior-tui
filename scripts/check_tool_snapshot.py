#!/usr/bin/env python3
"""Exercise an installed candidate's --check with synthetic HTTP, never live Jira."""

import os
import sys
import tempfile
from contextlib import redirect_stdout
from functools import partial
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

import jira_overview
from jira_overview.__main__ import main as cli


def main():
    if not Path(jira_overview.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("snapshot check did not import the installed candidate")
    fields = [{"id": field, "schema": {"custom": "com.pyxis.greenhopper.jira:" + kind}}
              for field, kind in (("customfield_123", "gh-sprint"),
                                  ("customfield_456", "gh-epic-label"),
                                  ("customfield_789", "gh-epic-link"))]
    responses = {
        "/jira/rest/api/2/myself": {"key": "synthetic-user", "displayName": "Synthetic User"},
        "/jira/rest/api/2/field": fields,
        "/jira/rest/api/2/search": {
            "startAt": 0, "total": 1, "issues": [{"id": "1", "key": "DEMO-1", "fields": {
                "summary": "Synthetic task", "status": {"name": "Open"},
                "customfield_123": [{"id": 7}], "customfield_456": None,
                "customfield_789": None}}]},
        "/jira/rest/agile/1.0/sprint/7": {"id": 7, "name": "Synthetic sprint", "state": "active"},
        "/jira/rest/api/2/issue/1/comment": {
            "startAt": 0, "total": 1, "comments": [{"id": "10", "author": {"key": "other"},
                                                     "created": "2026-01-01T12:00:00Z"}]},
    }
    requested = []

    def respond(request):
        assert request.method == "GET"
        assert request.url.host == "jira.example.invalid"
        assert request.headers.get("Authorization") == "Bearer synthetic-update-token"
        requested.append(request.url.path)
        return httpx.Response(200, json=responses[request.url.path])

    with tempfile.TemporaryDirectory(prefix="jirawarrior-snapshot-check-") as temporary:
        root = Path(temporary)
        state = root / "state"
        state.mkdir()
        baseline = state / "existing.json"
        baseline.write_bytes(b"synthetic-state-must-not-change\n")
        before = {p.name: p.read_bytes() for p in state.iterdir()}
        config = root / "config.toml"
        config.write_text('url = "https://jira.example.invalid/jira"\n'
                          'token_env = "JW_UPDATE_SYNTHETIC_TOKEN"\n'
                          f'state_dir = "{state.as_posix()}"\n')
        output = StringIO()
        with patch.dict(os.environ, {"JW_UPDATE_SYNTHETIC_TOKEN": "synthetic-update-token",
                                    "XDG_CONFIG_HOME": temporary, "XDG_STATE_HOME": temporary}), \
                patch.object(sys, "argv", ["jirawarrior", "--check", "--config", str(config)]), \
                patch("httpx.AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))), \
                patch("jira_overview.__main__.Overview", side_effect=AssertionError("--check started TUI")), \
                redirect_stdout(output):
            result = cli()
        assert result == 0, "installed synthetic snapshot --check failed"
        assert "GET-проверка успешна: задач 1, в активных спринтах 1." in output.getvalue()
        assert sorted(requested) == sorted(responses), "snapshot did not load all synthetic data"
        assert {p.name: p.read_bytes() for p in state.iterdir()} == before, "--check changed state"
    print("Installed synthetic snapshot --check passed; no live Jira or state writes.")


if __name__ == "__main__":
    main()
