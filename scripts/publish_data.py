"""Publish generated radar data without deploying or changing the website."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def api_request(url: str, token: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def publish(root: Path) -> None:
    token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("RADAR_DATA_BRANCH", "radar-state")
    api = f"https://api.github.com/repos/{repository}/contents"
    for relative in ("data/report.json", "data/digest.json"):
        path = root / relative
        encoded = base64.b64encode(path.read_bytes()).decode()
        current_sha = None
        try:
            current = api_request(f"{api}/{relative}?ref={branch}", token)
            current_sha = current.get("sha")
        except HTTPError as error:
            if error.code != 404:
                raise
        payload = {
            "message": "chore: update independent radar data",
            "content": encoded,
            "branch": branch,
        }
        if current_sha:
            payload["sha"] = current_sha
        api_request(f"{api}/{relative}", token, "PUT", payload)
        print(f"published {relative} to {branch}")


if __name__ == "__main__":
    publish(Path(__file__).resolve().parents[1])
