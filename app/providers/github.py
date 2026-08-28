from __future__ import annotations
import re
from typing import Any
import httpx
from app.providers.base import ResearchExtractor
class GitHubError(Exception):
    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
class GitHubProvider(ResearchExtractor):
    def __init__(self, token: str | None = None) -> None:
        self.base_url = "https://api.github.com"
        self.headers: dict[str, str] = {"Accept": "application/vnd.github+json", "User-Agent": "content-agent"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        with httpx.Client(base_url=self.base_url, headers=self.headers, timeout=30, follow_redirects=True) as client:
            resp = getattr(client, method)(url, **kwargs)
        return resp
    def _raise_for_status(self, resp: httpx.Response, context: str) -> None:
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = ""
            try:
                body = exc.response.json()
            except Exception:
                body = exc.response.text[:200]
            message = body.get("message", "") if isinstance(body, dict) else ""
            if status == 404:
                raise GitHubError(
                    f"GitHub {context} failed: repository not found, private without permission, or URL is invalid.",
                    status_code=status,
                    detail=message,
                ) from exc
            if status == 403:
                if "rate limit" in message.lower():
                    raise GitHubError(
                        f"GitHub {context} failed: rate limit exceeded. Consider setting GITHUB_TOKEN.",
                        status_code=status,
                        detail=message,
                    ) from exc
                raise GitHubError(
                    f"GitHub {context} failed: permission denied or rate limit exceeded.",
                    status_code=status,
                    detail=message,
                ) from exc
            if status == 401:
                raise GitHubError(
                    f"GitHub {context} failed: invalid or missing GITHUB_TOKEN.",
                    status_code=status,
                    detail=message,
                ) from exc
            raise GitHubError(
                f"GitHub {context} failed: HTTP {status}",
                status_code=status,
                detail=message,
            ) from exc
    def repo(self, url: str) -> dict:
        match = re.search(r"github\.com/([^/]+)/([^/]+)/?", url)
        if not match:
            raise ValueError("Invalid GitHub URL")
        owner, repo = match.group(1), match.group(2).removesuffix(".git")
        resp = self._request("get", f"/repos/{owner}/{repo}")
        self._raise_for_status(resp, f"fetch repo {owner}/{repo}")
        return resp.json()
    def readme(self, owner: str, repo: str) -> str:
        resp = self._request("get", f"/repos/{owner}/{repo}/readme", params={"accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            return ""
        self._raise_for_status(resp, f"fetch readme {owner}/{repo}")
        data = resp.json()
        if data.get("encoding") == "base64" and data.get("content"):
            import base64
            try:
                return base64.b64decode(data["content"].replace("\\n", "\n")).decode("utf-8", errors="ignore")
            except Exception:
                return ""
        return data.get("name", "")
