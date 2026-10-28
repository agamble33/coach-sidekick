"""Thin client for the Meta Model API. All network I/O goes through one
injectable `transport` so every caller can be tested offline.

transport(method, url, headers, body) -> (status: int, body: bytes)
"""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
from typing import Callable, Mapping

from .config import Settings

Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]


class MetaAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Meta API {status}: {message}")
        self.status = status


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                     timeout: float = 120.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def encode_multipart(fields: Mapping[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    """fields: name -> (filename or '', data, content_type). Returns (body, content_type)."""
    boundary = "----muse-replay-" + secrets.token_hex(12)
    out = bytearray()
    for name, (filename, data, ctype) in fields.items():
        out += f"--{boundary}\r\n".encode()
        disp = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disp += f'; filename="{filename}"'
        out += f"{disp}\r\nContent-Type: {ctype}\r\n\r\n".encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class MetaClient:
    def __init__(self, settings: Settings, transport: Transport | None = None):
        if not settings.meta_configured:
            raise MetaAPIError(0, "META_API_KEY and META_BASE_URL are required")
        self._key = settings.meta_api_key
        self.base_url = settings.meta_base_url
        self._transport = transport or urllib_transport

    def __repr__(self) -> str:                       # never leak the key
        return f"MetaClient(base_url={self.base_url!r})"

    def _headers(self, content_type: str | None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _call(self, method: str, path: str, body: bytes | None, content_type: str | None) -> dict:
        status, raw = self._transport(method, self.base_url + path, self._headers(content_type), body)
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            data = {"raw": raw[:200].decode("utf-8", "replace")}
        if status >= 400:
            msg = data.get("error", data.get("message", data.get("raw", "")))
            if isinstance(msg, dict):
                msg = msg.get("message", str(msg))
            raise MetaAPIError(status, str(msg)[:300])
        return data

    def post_json(self, path: str, payload: dict) -> dict:
        return self._call("POST", path, json.dumps(payload).encode(), "application/json")

    def post_multipart(self, path: str, fields: Mapping[str, tuple[str, bytes, str]]) -> dict:
        body, ctype = encode_multipart(fields)
        return self._call("POST", path, body, ctype)

    def get(self, path: str) -> dict:
        return self._call("GET", path, None, None)

    def list_models(self) -> list[str]:
        return [m["id"] for m in self.get("/models").get("data", [])]
