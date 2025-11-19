from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Any, Dict
import httpx, json, base64

def _now(): return datetime.now(timezone.utc)

def _decode_exp(access_token: str) -> Optional[datetime]:
    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "==="
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        if "exp" in payload:
            return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except Exception:
        pass
    return None

def _extract_tokens(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(data, dict):
        return None, None
    # flat
    access = data.get("access") or data.get("access_token") or data.get("token")
    refresh = data.get("refresh") or data.get("refresh_token")
    if access or refresh:
        return access, refresh
    # nested: tokens
    tokens = data.get("tokens")
    if isinstance(tokens, dict):
        access = tokens.get("access") or tokens.get("access_token") or tokens.get("token")
        refresh = tokens.get("refresh") or tokens.get("refresh_token")
        if access or refresh:
            return access, refresh
    # nested: data/result
    nested = data.get("data") or data.get("result")
    if isinstance(nested, dict):
        access = nested.get("access") or nested.get("access_token") or nested.get("token")
        refresh = nested.get("refresh") or nested.get("refresh_token")
        if access or refresh:
            return access, refresh
    return None, None

@dataclass
class JWTSession:
    base_url: str
    username: str
    password: str
    token_url: str = "/api/users/login/"
    refresh_url: str = "/api/users/token/refresh/"     
    timeout: float = 15.0

    access: Optional[str] = None
    refresh: Optional[str] = None
    access_exp: Optional[datetime] = None

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, headers={"Accept": "application/json"})

    def login(self):
        url = self.base_url.rstrip("/") + self.token_url
        with self._client() as c:
            r = c.post(url, json={"username": self.username, "password": self.password})
            r.raise_for_status()
            data = r.json()
            access, refresh = _extract_tokens(data)
            if not access:
                raise RuntimeError(f"Login OK nhưng không thấy access token: {data}")
            self.access = access
            self.refresh = refresh
            self.access_exp = _decode_exp(self.access) or (_now() + timedelta(minutes=4))

    def refresh_access(self):
        # Nếu không có refresh_url hoặc không có refresh token -> login lại
        if not self.refresh or not self.refresh_url:
            self.login(); return
        url = self.base_url.rstrip("/") + self.refresh_url
        with self._client() as c:
            r = c.post(url, json={"refresh": self.refresh})
            if r.status_code >= 400:
                r = c.post(url, json={"refresh_token": self.refresh})
            r.raise_for_status()
            data = r.json()
            access, _ = _extract_tokens(data)
            if not access:
                access = data.get("access") or data.get("access_token")
            if not access:
                raise RuntimeError(f"Refresh OK nhưng không thấy access token: {data}")
            self.access = access
            self.access_exp = _decode_exp(self.access) or (_now() + timedelta(minutes=4))

    def ensure_access(self):
        if not self.access or not self.access_exp or (_now() + timedelta(seconds=60) >= self.access_exp):
            if self.refresh and self.refresh_url:
                self.refresh_access()
            else:
                self.login()

    def auth_header(self) -> dict:
        self.ensure_access()
        return {"Authorization": f"Bearer {self.access}"}
