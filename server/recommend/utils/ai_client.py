# server/recommend/utils/ai_client.py
from __future__ import annotations

import os
import time
import json
from typing import Dict, Any, List, Optional

import requests
from django.conf import settings

# ---- Config ----
AI_BASE_URL   = os.getenv("AI_BASE_URL", getattr(settings, "AI_BASE_URL", "http://localhost:8001/api/ai")).rstrip("/")
AI_JWT_URL    = os.getenv("AI_JWT_URL", getattr(settings, "AI_JWT_URL", f"{AI_BASE_URL}/token/"))
AI_JWT_REFRESH_URL = os.getenv("AI_JWT_REFRESH_URL", getattr(settings, "AI_JWT_REFRESH_URL", f"{AI_BASE_URL}/token/refresh/"))
AI_JWT_USERNAME = os.getenv("AI_JWT_USERNAME", "be_service")
AI_JWT_PASSWORD = os.getenv("AI_JWT_PASSWORD", "portgasDace")
AI_HTTP_TIMEOUT = float(os.getenv("AI_HTTP_TIMEOUT", "10"))

# ---- Simple in-memory cache ----
_TOKEN_CACHE: Dict[str, Any] = {
    "access": None,
    "refresh": None,
    "exp": 0,  # epoch seconds
}

def _now() -> int:
    return int(time.time())

def _jwt_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

def _obtain_token() -> bool:
    """Get new access & refresh token."""
    try:
        resp = requests.post(
            AI_JWT_URL,
            json={"username": AI_JWT_USERNAME, "password": AI_JWT_PASSWORD},
            timeout=AI_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            print("[AI JWT] obtain failed:", resp.status_code, resp.text[:200])
            return False
        data = resp.json()
        _TOKEN_CACHE["access"] = data.get("access")
        _TOKEN_CACHE["refresh"] = data.get("refresh")
        # Không có exp trong payload response, ước lượng bằng lifetime (30 phút)
        _TOKEN_CACHE["exp"] = _now() + 25 * 60  # buffer 25'
        return True
    except Exception as e:
        print("[AI JWT] obtain exception:", e)
        return False

def _refresh_token() -> bool:
    """Refresh access token using refresh token."""
    if not _TOKEN_CACHE.get("refresh"):
        return _obtain_token()
    try:
        resp = requests.post(
            AI_JWT_REFRESH_URL,
            json={"refresh": _TOKEN_CACHE["refresh"]},
            timeout=AI_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            print("[AI JWT] refresh failed:", resp.status_code, resp.text[:200])
            # refresh hỏng -> obtain lại
            return _obtain_token()
        data = resp.json()
        _TOKEN_CACHE["access"] = data.get("access")
        _TOKEN_CACHE["exp"] = _now() + 25 * 60
        return True
    except Exception as e:
        print("[AI JWT] refresh exception:", e)
        return _obtain_token()

def _get_valid_token() -> Optional[str]:
    """Return a valid access token, refresh/obtain if needed."""
    if not _TOKEN_CACHE["access"] or _now() >= _TOKEN_CACHE["exp"]:
        ok = _refresh_token() if _TOKEN_CACHE["refresh"] else _obtain_token()
        if not ok:
            return None
    return _TOKEN_CACHE["access"]
    
# ==== PUBLIC CLIENT FUNCTIONS ====

def ai_fetch_predictions(
    snapshot_id: str,
    features_uri: Optional[str] = None,
    enrollment_ids: Optional[List[int]] = None,
    timeout: int = 60
) -> List[Dict[str, Any]]:
    """
    Call AI /api/predict with JWT auth.
    Returns: [{"enrollment_id": int, "p_hat": float}, ...]
    """
    url = AI_BASE_URL.rstrip("/") + "/predict"
    payload: Dict[str, Any] = {"snapshot_id": snapshot_id}
    if features_uri:
        payload["features_uri"] = features_uri
    if enrollment_ids:
        payload["enrollment_ids"] = enrollment_ids

    token = _get_valid_token()
    if not token:
        print("[AI] No JWT token available.")
        return []

    try:
        resp = requests.post(url, json=payload, headers=_jwt_headers(token), timeout=timeout)
        # token có thể hết hạn sớm → thử refresh 1 lần
        if resp.status_code in (401, 403):
            if _refresh_token():
                resp = requests.post(url, json=payload, headers=_jwt_headers(_TOKEN_CACHE["access"]), timeout=timeout)
        if resp.status_code != 200:
            print("[AI PREDICT] HTTP", resp.status_code, resp.text[:200])
            return []
        data = resp.json()
        return data.get("predictions", [])
    except Exception as e:
        print("[AI PREDICT] exception:", e)
        return []

# Nếu muốn unify sang JWT cho train/ingest luôn, có thể viết tương tự:
def ai_ingest_snapshot(snapshot_id: str, manifest: dict) -> bool:
    url = AI_BASE_URL.rstrip("/") + "/ingest/snapshot"
    token = _get_valid_token()
    if not token:
        return False
    try:
        resp = requests.post(url, json={"snapshot_id": snapshot_id, "manifest": manifest},
                             headers=_jwt_headers(token), timeout=AI_HTTP_TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False

def ai_trigger_train(snapshot_id: str, params: Optional[dict] = None) -> bool:
    url = AI_BASE_URL.rstrip("/") + "/train"
    token = _get_valid_token()
    if not token:
        print("[AI TRAIN] missing token")
        return False
    try:
        resp = requests.post(url, json={"snapshot_id": snapshot_id, "params": params or {}},
                             headers=_jwt_headers(token), timeout=AI_HTTP_TIMEOUT)
        if resp.status_code != 200:
            print("[AI TRAIN] HTTP", resp.status_code, resp.text[:500])
            return False
        return True
    except Exception as e:
        print("[AI TRAIN] exception:", e)
        return False

