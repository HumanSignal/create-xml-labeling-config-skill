#!/usr/bin/env python3
"""
Push a validated XML labeling config to a running Label Studio instance.

By default creates a NEW project from the config. With `--project-id`,
updates the label_config of an EXISTING project — handy when iterating
on a labeling interface for a project that already has tasks.

This script assumes the config has already been validated. Run
`validate_config.py --server <config.xml>` first; the SKILL.md
workflow handles ordering.

Usage:
    # Create a new project
    python3 push_config.py <config.xml> --title "My new project"

    # Update an existing project's label config
    python3 push_config.py <config.xml> --project-id 42

    # Dry-run (build the request, don't send)
    python3 push_config.py <config.xml> --title "Test" --dry-run

Reads `LABEL_STUDIO_URL` (default http://localhost:8080) and
`LABEL_STUDIO_API_KEY` from `.env` at the skill root or env.

Exits 0 on success, prints the project URL to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_env_from_dotenv() -> None:
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        env_path = candidate / ".env"
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)
            return


def _http(method: str, url: str, token: str,
          payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode() or "{}"
            return resp.status, json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return e.code, parsed
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach Label Studio at {url}: {e.reason}. "
            f"Is LS running and LABEL_STUDIO_URL set correctly?"
        ) from e


def _format_error(body: dict) -> str:
    if isinstance(body, dict):
        for key in ("label_config", "detail", "non_field_errors"):
            if key in body:
                val = body[key]
                if isinstance(val, list):
                    return "; ".join(str(v) for v in val)
                return str(val)
    return json.dumps(body)


def create_project(ls_url: str, token: str, title: str, description: str,
                   label_config: str) -> dict:
    url = f"{ls_url}/api/projects/"
    payload = {
        "title": title,
        "description": description,
        "label_config": label_config,
    }
    status, body = _http("POST", url, token, payload)
    if status not in (200, 201):
        raise RuntimeError(
            f"Label Studio rejected project creation (HTTP {status}): "
            f"{_format_error(body)}"
        )
    return body


def update_project_config(ls_url: str, token: str, project_id: int,
                          label_config: str) -> dict:
    url = f"{ls_url}/api/projects/{project_id}/"
    payload = {"label_config": label_config}
    status, body = _http("PATCH", url, token, payload)
    if status not in (200, 202):
        raise RuntimeError(
            f"Label Studio rejected config update for project "
            f"{project_id} (HTTP {status}): {_format_error(body)}"
        )
    return body


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        help="Path to the XML config file, or `-` to read from stdin.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Project title (required when creating a new project).",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Project description (optional).",
    )
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help=(
            "Update the label_config of an existing project instead of "
            "creating a new one. If the project already has annotations, "
            "Label Studio applies a soft-validation check — keep the "
            "object/control names stable to avoid invalidating existing "
            "results."
        ),
    )
    parser.add_argument(
        "--label-studio-url",
        default=None,
        help="Override LABEL_STUDIO_URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request that would be sent and exit 0.",
    )
    args = parser.parse_args(argv)

    _load_env_from_dotenv()

    config_text = (
        sys.stdin.read() if args.config == "-" else Path(args.config).read_text()
    )

    if args.project_id is None and not args.title:
        parser.error(
            "--title is required when creating a new project (omit "
            "--project-id to create, or pass --project-id <id> to update "
            "an existing project)."
        )

    ls_url = (
        args.label_studio_url
        or os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
    ).rstrip("/")
    token = os.environ.get("LABEL_STUDIO_API_KEY", "")
    if not token:
        print(
            "ERROR: LABEL_STUDIO_API_KEY is not set. Add it to .env or "
            "the environment. Get the token from your LS Account page.",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        if args.project_id is not None:
            print(
                f"DRY RUN: would PATCH {ls_url}/api/projects/"
                f"{args.project_id}/ with new label_config "
                f"({len(config_text)} chars)."
            )
        else:
            print(
                f"DRY RUN: would POST {ls_url}/api/projects/ "
                f"with title=\"{args.title}\", "
                f"description=\"{args.description}\", "
                f"label_config ({len(config_text)} chars)."
            )
        return 0

    try:
        if args.project_id is not None:
            body = update_project_config(
                ls_url, token, args.project_id, config_text
            )
            pid = args.project_id
            action = "Updated"
        else:
            body = create_project(
                ls_url, token, args.title, args.description, config_text
            )
            pid = body.get("id")
            action = "Created"
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    project_url = f"{ls_url}/projects/{pid}/data"
    print(f"{action} project {pid}: {project_url}")
    print(json.dumps(
        {"project_id": pid, "url": project_url, "title": body.get("title")},
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
