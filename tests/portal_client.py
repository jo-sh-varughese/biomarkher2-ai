"""A real portal server on an ephemeral port, and clients that talk to it the
way the browser does: a session cookie from sign-in, and the session's CSRF
token on every state-changing request."""

from __future__ import annotations

import http.client
import json
import threading
from dataclasses import dataclass
from http.server import ThreadingHTTPServer

TEST_PASSWORD = "correct horse battery staple"


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes

    @property
    def json(self):
        return json.loads(self.body)


class Client:
    """One browser: its own cookie jar and CSRF token."""

    def __init__(self, port: int):
        self.port = port
        self.cookie: str | None = None
        self.csrf: str | None = None

    def send(self, method: str, path: str, body=None, *, headers: dict | None = None,
             csrf: bool = True) -> Response:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        sent = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            sent["Content-Type"] = "application/json"
        if self.cookie:
            sent["Cookie"] = self.cookie
        if csrf and self.csrf and method != "GET":
            sent["X-CSRF-Token"] = self.csrf
        sent.update(headers or {})
        conn.request(method, path, body=payload, headers=sent)
        response = conn.getresponse()
        data = response.read()
        received = {name.lower(): value for name, value in response.getheaders()}
        set_cookie = response.getheader("Set-Cookie")
        if set_cookie:
            self.cookie = None if "Max-Age=0" in set_cookie else set_cookie.split(";", 1)[0]
        conn.close()
        return Response(response.status, received, data)

    def login(self, email: str, password: str = TEST_PASSWORD, **extra) -> Response:
        response = self.send("POST", "/api/auth/login", {"email": email, "password": password, **extra})
        if response.status == 200:
            self.csrf = response.json["csrf"]
        return response


class Running:
    """A server for the duration of a with-block, signed in as a user of
    `role` unless sign_in is False -- every API route except the sign-in
    routes needs a session."""

    def __init__(self, state, *, sign_in: bool = True, role: str = "admin", name: str = "AB",
                 email: str | None = None):
        self.state = state
        self.sign_in = sign_in
        self.role = role
        self.name = name
        self.email = email or f"{role}@example.org"
        self.user: dict | None = None

    def __enter__(self) -> "Running":
        from app.server import Handler

        Handler.state = self.state
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]
        self.browser = Client(self.port)
        if self.sign_in:
            self.user = self.state.auth.create_user(
                email=self.email, name=self.name, role=self.role, password=TEST_PASSWORD
            )
            response = self.browser.login(self.email)
            assert response.status == 200, response.body
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    def client(self) -> Client:
        """A second browser against the same server, signed out."""
        return Client(self.port)

    def send(self, method: str, path: str, body=None, **kwargs) -> Response:
        return self.browser.send(method, path, body, **kwargs)

    def request(self, method: str, path: str, body=None):
        """(status, content type, body) -- the shape the older tests use."""
        response = self.browser.send(method, path, body)
        return response.status, response.headers.get("content-type", ""), response.body
