import base64
import hashlib
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

import click
import httpx

MCP_URL = "https://api.wisprflow.ai/connect/mcp"
AUTH = "https://mcp-auth.wisprflow.com/oauth2"
SCOPE = "openid offline_access email profile"
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
PROTOCOL = "2025-06-18"
STATE = Path(os.environ.get("WISPR_CONFIG", Path.home() / ".config" / "wispr" / "auth.json"))


class AuthError(click.ClickException):
    exit_code = 4


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.touch(mode=0o600)
    STATE.write_text(json.dumps(state, indent=2))


def register() -> str:
    r = httpx.post(
        f"{AUTH}/register",
        json={
            "client_name": "wispr-cli",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPE,
        },
    )
    r.raise_for_status()
    return r.json()["client_id"]


def store_tokens(state: dict, tok: dict) -> dict:
    state["access_token"] = tok["access_token"]
    state["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    if tok.get("refresh_token"):
        state["refresh_token"] = tok["refresh_token"]
    save(state)
    return state


def wait_for_callback() -> dict:
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(parse_qsl(urlparse(self.path).query))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Wispr login done. You can close this tab.")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    server.timeout = 5
    deadline = time.time() + 300
    try:
        while "code" not in got and "error" not in got:
            if time.time() > deadline:
                raise AuthError("login timed out")
            server.handle_request()
    finally:
        server.server_close()
    return got


def browser_login(show, paste=None) -> dict:
    state = load()
    if "client_id" not in state:
        state["client_id"] = register()
        save(state)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    nonce = secrets.token_urlsafe(16)
    url = f"{AUTH}/authorize?" + urlencode(
        {
            "response_type": "code",
            "client_id": state["client_id"],
            "redirect_uri": REDIRECT,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": nonce,
            "resource": MCP_URL,
        }
    )
    show(url)
    if paste:
        got = dict(parse_qsl(urlparse(paste().strip()).query))
    else:
        got = wait_for_callback()
    if "error" in got:
        raise AuthError(f"login failed: {got}")
    if got.get("state") != nonce:
        raise AuthError("login failed: state mismatch")
    r = httpx.post(
        f"{AUTH}/token",
        data={
            "grant_type": "authorization_code",
            "code": got["code"],
            "redirect_uri": REDIRECT,
            "client_id": state["client_id"],
            "code_verifier": verifier,
            "resource": MCP_URL,
        },
    )
    if r.status_code != 200:
        raise AuthError(f"token exchange failed: {r.text}")
    return store_tokens(state, r.json())


def token(refresh=False) -> str:
    state = load()
    if "access_token" not in state:
        raise AuthError("not logged in; run `wispr login`")
    if not refresh and time.time() < state["expires_at"]:
        return state["access_token"]
    if "refresh_token" not in state:
        raise AuthError("session expired; run `wispr login`")
    r = httpx.post(
        f"{AUTH}/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": state["refresh_token"],
            "client_id": state["client_id"],
            "resource": MCP_URL,
        },
    )
    if r.status_code != 200:
        raise AuthError(f"refresh failed ({r.status_code}); run `wispr login`")
    return store_tokens(state, r.json())["access_token"]


class MCP:
    def __init__(self):
        self.http = httpx.Client(
            timeout=60,
            headers={
                "Authorization": f"Bearer {token()}",
                "Accept": "application/json, text/event-stream",
            },
        )
        self.next_id = 0
        init = self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "wispr-cli", "version": "0.1.0"},
            },
        )
        self.http.headers["MCP-Protocol-Version"] = init["protocolVersion"]
        self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def post(self, body: dict) -> httpx.Response:
        r = self.http.post(MCP_URL, json=body)
        if r.status_code == 401:
            self.http.headers["Authorization"] = f"Bearer {token(refresh=True)}"
            r = self.http.post(MCP_URL, json=body)
        if r.status_code == 401:
            raise AuthError("token rejected; run `wispr login`")
        r.raise_for_status()
        if sid := r.headers.get("mcp-session-id"):
            self.http.headers["Mcp-Session-Id"] = sid
        return r

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        r = self.post({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            msgs = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
            msg = next(m for m in msgs if m.get("id") == self.next_id)
        else:
            msg = r.json()
        if "error" in msg:
            raise click.ClickException(f"{method}: {msg['error']['message']}")
        return msg["result"]

    def tools(self) -> list[dict]:
        return self.rpc("tools/list")["tools"]

    def call(self, name: str, args: dict) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": args})
