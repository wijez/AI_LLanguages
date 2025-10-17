from typing import Dict, Any, Iterable, Optional
import httpx
from ..auth.jwt_session import JWTSession

class BEClient:
    def __init__(
        self,
        base_url: str,
        jwt_session: JWTSession,
        timeout: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.jwt = jwt_session
        self.timeout = timeout

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        headers.update(self.jwt.auth_header())
        with httpx.Client(timeout=self.timeout, headers=headers) as cli:
            r = cli.get(url, params=params)
            if r.status_code == 401:
                # thử login lại 1 lần
                self.jwt.login()
                headers.update(self.jwt.auth_header())
                r = cli.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r.json()

    def paginate(
        self,
        path: str,
        params: Dict[str, Any],
        page_field: str = "results",
        page_param: str = "page",
        page_size: int = 500,
    ) -> Iterable[Dict[str, Any]]:
        page = 1
        while True:
            q = dict(params); q.update({page_param: page, "page_size": page_size})
            data = self._get(path, q)
            items = data.get(page_field, data)
            if not items:
                break
            for x in items:
                yield x
            if data.get("next"):
                page += 1
            else:
                break

    # endpoint path
    def list_mistakes(self, user_id: int, language: str, since: Optional[str] = None):
        params = {"user_id": user_id, "language": language}
        if since: params["since"] = since
        return self.paginate("/api/mistake/", params)

    def list_interactions(self, user_id: int, language: str, since: Optional[str] = None):
        params = {"user_id": user_id, "language": language}
        if since: params["since"] = since
        return self.paginate("/api/learning-interaction/", params)

    def list_skill_stats(self, user_id: int, language: str):
        params = {"user_id": user_id, "language": language}
        return self.paginate("/api/skill-stats/", params)  
