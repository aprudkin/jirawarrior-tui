"""Synthetic TOML configuration; no Jira requests or private configuration."""
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

from jira_overview.__main__ import configuration, main
from jira_overview.core import Issue, Jira, OverviewError


class ConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_refresh_interval_is_one_hour(self):
        await self.assert_interval(None, 3600)

    async def test_explicit_refresh_interval_still_overrides_default(self):
        for interval in (5, 60, 3600, 86400):
            with self.subTest(interval=interval):
                await self.assert_interval(interval, interval)

    async def test_invalid_urls_fail_before_client_or_ui_without_leaking_details(self):
        for authority in ("jira.example.invalid:wrong", "jira.example.invalid:65536",
                          "jira.example.invalid:-1", "[broken"):
            url = f"https://{authority}/private-jira"
            with self.subTest(url=url), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "config.toml"
                config.write_text(f'url = "{url}"\ntoken_env = "SYNTHETIC_PAT"\n')
                with patch.dict(os.environ, {"SYNTHETIC_PAT": "synthetic-secret"}), \
                        patch("jira_overview.core.httpx.AsyncClient") as client, \
                        patch("jira_overview.__main__.Overview") as overview:
                    with self.assertRaises(OverviewError) as raised:
                        configuration(config)
                    for check in ([], ["--check"]):
                        output = StringIO()
                        with patch.object(sys, "argv", ["jw", "--config", str(config), *check]), \
                                redirect_stderr(output):
                            self.assertEqual(main(), 1)
                        self.assertIn("URL Jira", output.getvalue())
                        for sensitive in (url, authority, "private-jira", "synthetic-secret", "Traceback"):
                            self.assertNotIn(sensitive, output.getvalue())
                    self.assertNotIn(url, str(raised.exception))
                    client.assert_not_called()
                    overview.assert_not_called()

    async def test_valid_https_urls_keep_context_path_and_ports(self):
        for url in ("https://jira.example.invalid", "https://jira.example.invalid/jira",
                    "https://jira.example.invalid:443/jira", "https://jira.example.invalid:1/jira",
                    "https://jira.example.invalid:65535/jira", "https://[::1]:8443/jira"):
            with self.subTest(url=url):
                jira = Jira(url, "synthetic-token")
                try:
                    self.assertEqual(jira.url, url)
                    self.assertEqual(jira.browser_url(Issue("1", "DEMO-1", "Task", "Open", (), frozenset(), frozenset())),
                                     url + "/browse/DEMO-1")
                finally:
                    await jira.close()

    async def test_late_httpx_invalid_url_is_a_safe_overview_error(self):
        jira = Jira("https://jira.example.invalid/jira", "synthetic-token")
        try:
            with patch.object(jira.client, "get", side_effect=httpx.InvalidURL("private-url synthetic-token")), \
                    self.assertRaisesRegex(OverviewError, "URL Jira") as raised:
                await jira.snapshot()
            self.assertNotIn("private-url", str(raised.exception))
            self.assertNotIn("synthetic-token", str(raised.exception))
        finally:
            await jira.close()

    async def assert_interval(self, configured, expected):
        with tempfile.TemporaryDirectory(prefix="jira-config-") as directory:
            root = Path(directory)
            config = root / "config.toml"
            contents = ('url = "https://jira.example.invalid/jira"\n'
                        'token_env = "SYNTHETIC_HOURLY_PAT"\n')
            if configured is not None:
                contents += f"refresh_seconds = {configured}\n"
            config.write_text(contents)
            with patch.dict(os.environ, {"SYNTHETIC_HOURLY_PAT": "synthetic-token",
                                         "XDG_STATE_HOME": str(root / "state")}):
                jira, state_dir, interval = configuration(config)
            try:
                self.assertEqual(interval, expected)
                self.assertEqual(state_dir, root / "state/jira-overview")
                self.assertFalse(state_dir.exists())
            finally:
                await jira.close()


if __name__ == "__main__":
    unittest.main()
