"""Overview cli integration checks; synthetic Jira only."""
import asyncio
import unittest
from unittest.mock import patch

from support.jira import TOKEN
from support.overview import OverviewCase

from jira_overview.core import Jira, OverviewError


class OverviewCliTests(OverviewCase):
    async def test_check_command_success_and_failure_never_creates_state(self):
        import contextlib
        import io

        from jira_overview.__main__ import main
        def run_check():
            with patch("jira_overview.__main__.configuration", side_effect=lambda _: (
                    Jira(self.server.url, TOKEN, allow_local_http=True), self.state_dir, 60)), \
                    patch("sys.argv", ["jirawarrior", "--check", "--config", "synthetic.toml"]):
                return main()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = await asyncio.to_thread(run_check)
        self.assertEqual(result, 0)
        self.assertIn("GET-проверка успешна", output.getvalue())
        self.assertFalse(list(self.state_dir.iterdir()))
        self.server.status = 500
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = await asyncio.to_thread(run_check)
        self.assertEqual(result, 1)
        self.assertIn("HTTP 500", errors.getvalue())
        self.assertFalse(list(self.state_dir.iterdir()))

    async def test_cli_requires_tls_and_valid_configuration(self):
        from jira_overview.__main__ import configuration
        with self.assertRaises(OverviewError):
            Jira(self.server.url, TOKEN)
        config = self.state_dir / "config.toml"
        for contents in ('not TOML', 'url = "https://jira.example.org"',
                         'url = "https://jira.example.org"\ntoken_env = "MISSING_SYNTHETIC_TOKEN"'):
            config.write_text(contents)
            with self.assertRaises(OverviewError):
                configuration(config)


if __name__ == "__main__":
    unittest.main()
