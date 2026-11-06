"""Synthetic Jira HTTP server shared by API, session and UI tests."""
import json
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

TOKEN = "synthetic-token-never-persist"  # noqa: S105 — deliberately fake HTTP credential
BODY = "private-comment-body-never-persist"


def comment(cid, author="other"):
    return {"id": str(cid), "author": {"key": author}, "created": "2026-01-01T12:00:00Z", "body": BODY}


def issue(i, sprints=None, comments=None, summary=None, *, epic=False, epic_key=None, parent=None,
          updated=None):
    return {"id": str(i), "key": f"DEMO-{i}", "fields": {
        "summary": summary or f"Synthetic task {i}", "status": {"name": "In Progress"},
        "updated": updated,
        "issuetype": {"name": "Epic" if epic else "Task", "subtask": bool(parent)},
        "customfield_456": f"Большая работа {i}" if epic else None,
        "customfield_789": epic_key, "parent": {"key": parent} if parent else None,
        "customfield_123": sprints, "comment": {"comments": [], "total": 999}},
        "comments": comments if comments is not None else [comment(i * 10)]}


class Server:
    def __init__(self):
        self.issues = [issue(1, [{"id": 1}]), issue(2)]
        self.context_issues = []
        self.reject_unknown_verifying = False
        self.sprint_names = {}
        self.sprint_states = {}
        # Writes are opt-in for sprint-action tests; ordinary overview remains GET-only.
        self.sprint_post_status: int | None = None
        self.sprint_post_fail_refresh = False
        self.fields = [{"id": field, "schema": {"custom": "com.pyxis.greenhopper.jira:" + kind}}
                       for field, kind in (("customfield_123", "gh-sprint"),
                                           ("customfield_456", "gh-epic-label"),
                                           ("customfield_789", "gh-epic-link"))]
        self.fail_path: str | None = None
        self.user = "me"
        self.display_name = "Synthetic User"
        self.requests = []
        self.page_size = 1
        self.status = 200
        self.bad_json = False
        self.partial = False
        self.duplicate = False
        self.total_delta = 0
        self.bad_start = False
        self.delay: float = 0
        self.request_gate = False
        self.request_started = threading.Event()
        self.request_release = threading.Event()
        self.redirect: str | None = None
        self.retry_after = "1"
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path.removeprefix("/jira")
                params = parse_qs(parsed.query)
                fixture.requests.append(("GET", path, params, self.headers.get("Authorization")))
                if fixture.request_gate:
                    fixture.request_started.set()
                    fixture.request_release.wait(timeout=10)
                if fixture.delay:
                    time.sleep(fixture.delay)
                if fixture.redirect:
                    self.send_response(302)
                    self.send_header("Location", fixture.redirect)
                    self.end_headers()
                    return
                if fixture.status != 200 or path == fixture.fail_path:
                    self.send_response(fixture.status if fixture.status != 200 else 403)
                    self.send_header("Retry-After", fixture.retry_after)
                    self.end_headers()
                    self.wfile.write(b"SECRET RESPONSE BODY")
                    return
                if path == "/rest/api/2/myself":
                    data = {"key": fixture.user, "displayName": fixture.display_name}
                elif path == "/rest/api/2/field":
                    data = fixture.fields
                elif path == "/rest/api/2/search":
                    if fixture.reject_unknown_verifying and "verifying" in params.get("jql", [""])[0].casefold():
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b"Unknown status Verifying")
                        return
                    data = self.page(fixture.issues, "issues", params)
                elif path.startswith("/rest/agile/1.0/sprint/"):
                    sid = int(path.rsplit("/", 1)[1])
                    data = {"id": sid, "name": fixture.sprint_names.get(sid, f"Sprint {sid}"),
                            "state": fixture.sprint_states.get(sid, "closed" if sid == 3 else "active")}
                elif path.startswith("/rest/api/2/issue/") and path.endswith("/comment"):
                    iid = path.split("/")[-2]
                    data = self.page(next(i for i in fixture.issues if i["id"] == iid)["comments"], "comments", params)
                elif path.startswith("/rest/api/2/issue/"):
                    key = path.rsplit("/", 1)[1]
                    data = next((i for i in fixture.issues + fixture.context_issues
                                 if i["key"] == key or i["id"] == key), None)
                    if data is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                with suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(b"broken JSON secret" if fixture.bad_json else json.dumps(data).encode())

            def page(self, items, key, params):
                start = int(params.get("startAt", [0])[0])
                subset = items[start:start + fixture.page_size]
                if fixture.partial and start:
                    subset = []
                if fixture.duplicate and start:
                    subset = items[:fixture.page_size]
                total = len(items) + (fixture.total_delta if start else 0)
                start_at = start + (1 if fixture.bad_start and start else 0)
                return {key: subset, "total": total, "startAt": start_at, "maxResults": fixture.page_size}

            def do_POST(self):
                path = urlsplit(self.path).path.removeprefix("/jira")
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                fixture.requests.append(("POST", path, payload, self.headers.get("Authorization")))
                code = fixture.sprint_post_status or 405
                if code == 204 and path.startswith("/rest/agile/1.0/sprint/") and path.endswith("/issue"):
                    sid = path.split("/")[-2]
                    for item in fixture.issues:
                        if item["id"] in payload.get("issues", []):
                            item["fields"]["customfield_123"] = [{"id": int(sid)}]
                    if fixture.sprint_post_fail_refresh:
                        fixture.fail_path = "/rest/api/2/search"
                self.send_response(code)
                self.end_headers()

            def do_PUT(self):
                fixture.requests.append((self.command, self.path, {}, None))
                self.send_response(405)
                self.end_headers()

            do_DELETE = do_PATCH = do_PUT

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}/jira"

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
