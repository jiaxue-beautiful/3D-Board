"""Publish generated radar data without deploying or changing the website."""

from __future__ import annotations

import base64
import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from collect import atomic_json, instant


def restore(root: Path) -> None:
    """Never silently fall back to the stale code-branch snapshot."""
    repository = os.environ['GITHUB_REPOSITORY']
    branch = os.environ.get('RADAR_DATA_BRANCH', 'radar-state')
    current = api_request(
        f'https://api.github.com/repos/{repository}/contents/data/digest.json?ref={branch}',
        os.environ['GITHUB_TOKEN'])
    data = json.loads(base64.b64decode(current['content'], validate=False))
    if (data.get('version') != 1 or instant(data.get('checkedAt')) is None
            or any(not isinstance(data.get(k), list) for k in ('news', 'cases'))):
        raise ValueError('Invalid previous published digest; stop without overwriting')
    atomic_json(root / 'data/digest.json', data)
    print('Restored published digest:', data['checkedAt'])


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
    parser = argparse.ArgumentParser()
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    (restore if args.restore else publish)(Path(__file__).resolve().parents[1])
