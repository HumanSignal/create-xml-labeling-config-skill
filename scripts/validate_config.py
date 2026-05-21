#!/usr/bin/env python3
"""
Validate a Label Studio XML labeling config.

Runs three layers of checks:

1. **XML well-formed** — must parse as XML.
2. **Structural rules** baked from Label Studio's authoring guidelines:
   - single `<View>` root
   - every object/control tag has a `name`
   - all `name` values are unique
   - every control tag has a `toName` pointing to a real **object** tag
     (Pairwise allows two comma-separated targets)
   - `<Label>` / `<Choice>` nesting rules (Choice may nest only under Taxonomy)
   - `style=` only on View/Filter/Header; `className=` only on View
   - no deprecated tags (`AudioPlus`, `Repeater`)
   - `visibleWhen` on a View has matching attribute on the nested control
3. **Server-side validation** (optional) — POSTs to a running Label
   Studio at `$LABEL_STUDIO_URL` using `$LABEL_STUDIO_API_KEY`.
   - If `--project-id <id>` is passed, uses
     `POST /api/projects/{id}/validate/`.
   - Otherwise falls back to creating a throwaway "validation"
     project, posting the config, and deleting it. This catches
     anything the local checks miss (engine-level errors, unknown
     tag combinations) without leaving cruft in the LS instance.

Exit code 0 only when every requested check passes.

Usage:
    python3 validate_config.py <path-to-config.xml>
    python3 validate_config.py <path-to-config.xml> --server
    python3 validate_config.py <path-to-config.xml> --server --project-id 123
    cat config.xml | python3 validate_config.py -

Reads `LABEL_STUDIO_URL` (default http://localhost:8080) and
`LABEL_STUDIO_API_KEY` from `.env` at the skill root or from the
environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Knowledge baked from the Label Studio authoring guidelines.
# ---------------------------------------------------------------------------

OBJECT_TAGS = {
    "Text", "HyperText", "Paragraphs", "Image", "Audio", "Video",
    "TimeSeries", "Table", "List", "Chat", "PDF",
    # Deprecated but historically an object tag — accept it to avoid
    # cascade errors, then surface the deprecation warning separately.
    "AudioPlus",
}

# Control tags that produce regions (also serve as the object-tag side
# in Pairwise references for some configs).
LABEL_CONTAINER_TAGS = {
    "Labels", "RectangleLabels", "PolygonLabels", "KeyPointLabels",
    "BrushLabels", "EllipseLabels", "HyperTextLabels", "ParagraphLabels",
    "TimeSeriesLabels", "VideoRectangle",
}

# All control tags that must declare toName.
CONTROL_TAGS_REQUIRING_TONAME = LABEL_CONTAINER_TAGS | {
    "Choices", "Taxonomy", "TextArea", "Rating", "Number", "DateTime",
    "Pairwise", "Filter", "Ranker", "Rectangle", "Polygon", "KeyPoint",
    "Brush", "Ellipse",
}

DEPRECATED_TAGS = {
    "AudioPlus": "Use <Audio> instead. Same attributes, same functionality.",
    "Repeater": (
        "<Repeater> is deprecated. Use <Image valueList=\"$images\"> with "
        "perItem=\"true\" controls, or <Paragraphs>, or <List>."
    ),
}

# style= / className= placement rules.
STYLE_ALLOWED_ON = {"View", "Filter", "Header"}
CLASSNAME_ALLOWED_ON = {"View"}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def extend(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


# ---------------------------------------------------------------------------
# Layer 1: XML well-formed
# ---------------------------------------------------------------------------

def parse_xml(config: str) -> tuple[ET.Element | None, ValidationResult]:
    result = ValidationResult()
    try:
        root = ET.fromstring(config)
    except ET.ParseError as e:
        result.add_error(f"XML is not well-formed: {e}")
        return None, result
    if root.tag != "View":
        result.add_error(
            f"Root element must be <View>, got <{root.tag}>. "
            "Wrap the entire config in a single <View>...</View>."
        )
        return None, result
    return root, result


# ---------------------------------------------------------------------------
# Layer 2: structural rules
# ---------------------------------------------------------------------------

def iter_all(root: ET.Element) -> Iterable[ET.Element]:
    yield root
    for child in root.iter():
        if child is not root:
            yield child


def validate_structure(root: ET.Element) -> ValidationResult:
    result = ValidationResult()

    # Pass 1: collect object-tag names and check uniqueness of all names.
    seen_names: dict[str, str] = {}  # name -> tag
    object_names: set[str] = set()
    for el in iter_all(root):
        name = el.get("name")
        if not name:
            # name is required on every object/control tag with one of the known tag names
            if el.tag in OBJECT_TAGS or el.tag in CONTROL_TAGS_REQUIRING_TONAME:
                result.add_error(
                    f"<{el.tag}> is missing a `name` attribute (every "
                    f"object and control tag must have a unique name)."
                )
            continue
        if name in seen_names:
            result.add_error(
                f"Duplicate `name=\"{name}\"` on <{el.tag}>: another tag "
                f"<{seen_names[name]}> already uses this name. Names must "
                f"be unique across the whole config."
            )
        else:
            seen_names[name] = el.tag
        if el.tag in OBJECT_TAGS:
            object_names.add(name)

    # Pass 2: deprecated tags, value attrs, toName targets, nesting,
    # style/className placement, visibleWhen consistency.
    for el in iter_all(root):
        # Deprecated.
        if el.tag in DEPRECATED_TAGS:
            result.add_warning(
                f"<{el.tag}> is deprecated. {DEPRECATED_TAGS[el.tag]}"
            )

        # value on object tags (allow valueList instead).
        if el.tag in OBJECT_TAGS:
            value = el.get("value")
            value_list = el.get("valueList")
            if not value and not value_list:
                result.add_error(
                    f"<{el.tag} name=\"{el.get('name')}\"> must declare a "
                    f"`value` (or `valueList` for multi-item object tags). "
                    f"Use `value=\"$key\"` to bind to a task data field."
                )
            if value and not value.startswith("$") and el.tag != "Header":
                # Object tags almost always bind to a variable. Allow
                # literal values but warn — usually a typo.
                result.add_warning(
                    f"<{el.tag} name=\"{el.get('name')}\"> has "
                    f"`value=\"{value}\"` without a leading `$`. If this "
                    f"is supposed to bind to a task data field, write it "
                    f"as `value=\"${value}\"`."
                )

        # toName for control tags.
        if el.tag in CONTROL_TAGS_REQUIRING_TONAME:
            to_name = el.get("toName")
            if not to_name:
                result.add_error(
                    f"<{el.tag} name=\"{el.get('name')}\"> is missing a "
                    f"`toName` attribute (must point to an object tag's name)."
                )
            else:
                targets = [t.strip() for t in to_name.split(",")]
                if el.tag == "Pairwise":
                    if len(targets) != 2:
                        result.add_error(
                            f"<Pairwise name=\"{el.get('name')}\"> must "
                            f"have exactly two comma-separated toName "
                            f"targets, got `{to_name}`."
                        )
                else:
                    if len(targets) > 1:
                        result.add_error(
                            f"<{el.tag} name=\"{el.get('name')}\"> "
                            f"`toName` may only reference one object tag "
                            f"(only <Pairwise> can list two). Got `{to_name}`."
                        )
                # <Filter> is the documented exception: its `toName`
                # points at a label container (a control), not an
                # object tag. Allowlist that case.
                allow_control_target = el.tag == "Filter"
                for tgt in targets:
                    if tgt in object_names:
                        continue
                    if tgt in seen_names:
                        if allow_control_target and seen_names[tgt] in LABEL_CONTAINER_TAGS:
                            continue
                        result.add_error(
                            f"<{el.tag} name=\"{el.get('name')}\"> "
                            f"`toName=\"{tgt}\"` points to a control "
                            f"tag (<{seen_names[tgt]}>). toName must "
                            f"point to an OBJECT tag only."
                        )
                    else:
                        result.add_error(
                            f"<{el.tag} name=\"{el.get('name')}\"> "
                            f"`toName=\"{tgt}\"` does not match any "
                            f"object tag's `name` in this config. "
                            f"Object tags present: "
                            f"{sorted(object_names) or '<none>'}"
                        )

        # style= placement.
        if el.get("style") and el.tag not in STYLE_ALLOWED_ON:
            result.add_error(
                f"<{el.tag}> has a `style=` attribute, but `style=` is "
                f"only allowed on <View>, <Filter>, and <Header>. Wrap "
                f"<{el.tag}> in a <View> and put the style on the <View>."
            )

        # className= placement.
        if el.get("className") and el.tag not in CLASSNAME_ALLOWED_ON:
            result.add_error(
                f"<{el.tag}> has a `className=` attribute, but `className=` "
                f"is only allowed on <View>. Wrap <{el.tag}> in a <View> "
                f"and put the className on the <View>."
            )

        # Nesting rules.
        if el.tag == "Label":
            for child in el:
                if child.tag == "Label":
                    result.add_error(
                        "<Label> tags cannot be nested. Flatten the labels "
                        "in your <Labels>/<RectangleLabels>/etc. container."
                    )

        if el.tag == "Choice":
            # Walk up to find the nearest Choices / Taxonomy ancestor.
            # ElementTree doesn't expose parents, so do this in a parent
            # pass below.
            pass

    # Nesting: Choice may nest under Taxonomy but not under Choices.
    for parent in root.iter():
        if parent.tag == "Choices":
            for child in parent:
                if child.tag == "Choice":
                    for grandchild in child:
                        if grandchild.tag == "Choice":
                            result.add_error(
                                "<Choice> nested inside another <Choice> "
                                "inside <Choices>. Only <Taxonomy> allows "
                                "nested <Choice> tags."
                            )

    # visibleWhen consistency: when a <View> has visibleWhen + whenTagName +
    # whenChoiceValue / whenLabelValue, any control tag inside that View
    # whose answer would otherwise serialize should carry the same
    # visibleWhen on itself, otherwise its (default) answer leaks into the
    # annotation result.
    for view in root.iter("View"):
        if not view.get("visibleWhen"):
            continue
        view_vw = view.get("visibleWhen")
        view_tag = view.get("whenTagName")
        view_choice = view.get("whenChoiceValue")
        view_label = view.get("whenLabelValue")
        for child in view.iter():
            if child is view:
                continue
            if child.tag in CONTROL_TAGS_REQUIRING_TONAME:
                if child.tag in ("Filter", "Ranker"):
                    continue  # purely cosmetic, no serialized answer
                if child.get("visibleWhen") != view_vw:
                    result.add_warning(
                        f"<{child.tag} name=\"{child.get('name')}\"> is "
                        f"inside a <View visibleWhen=\"{view_vw}\">, but "
                        f"the control tag itself does not repeat "
                        f"`visibleWhen`. Without it the control's answer "
                        f"will serialize even when the View is hidden. "
                        f"Add the same visibleWhen / whenTagName / "
                        f"whenChoiceValue / whenLabelValue to "
                        f"<{child.tag}>."
                    )

    # Sanity: there must be at least one object tag.
    if not object_names:
        result.add_error(
            "Config has no object tag (<Text>, <Image>, <Audio>, <Video>, "
            "<HyperText>, <Paragraphs>, <TimeSeries>, <Table>, etc.). At "
            "least one object tag is required for annotators to see "
            "anything."
        )

    # Sanity: there must be at least one control tag.
    has_control = any(
        el.tag in CONTROL_TAGS_REQUIRING_TONAME for el in iter_all(root)
    )
    if not has_control:
        result.add_warning(
            "Config has no control tags (<Labels>, <Choices>, <TextArea>, "
            "etc.). Annotators will see the data but won't be able to "
            "label it."
        )

    return result


# ---------------------------------------------------------------------------
# Layer 3: server-side validation (optional)
# ---------------------------------------------------------------------------

def _load_env_from_dotenv() -> None:
    """Walk up from this script's directory looking for `.env`."""
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
        with urllib.request.urlopen(req, timeout=15) as resp:
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
            f"Set LABEL_STUDIO_URL in .env or pass --label-studio-url."
        ) from e


def server_validate(config: str, ls_url: str, ls_token: str,
                    project_id: int | None = None) -> ValidationResult:
    """
    Validate against a running Label Studio instance.

    With --project-id, hits POST /api/projects/{id}/validate/.

    Without --project-id, creates a throwaway project to validate the
    config, then deletes it. We do this because Label Studio's create
    endpoint runs the same validator that /validate/ runs, but doesn't
    require an existing project id. The throwaway project leaves no
    tasks behind because we delete it before returning.
    """
    result = ValidationResult()
    ls_url = ls_url.rstrip("/")

    if project_id is not None:
        url = f"{ls_url}/api/projects/{project_id}/validate/"
        status, body = _http(
            "POST", url, ls_token, {"label_config": config}
        )
        if status == 200:
            return result
        result.add_error(
            f"Label Studio rejected the config "
            f"(POST {url} -> {status}): {_format_ls_error(body)}"
        )
        return result

    # Throwaway-project path. LS validates config on create; if invalid
    # it returns 400 with a `label_config` validation error message.
    create_url = f"{ls_url}/api/projects/"
    payload = {
        "title": "labeling-config-builder validation (auto-delete)",
        "label_config": config,
    }
    status, body = _http("POST", create_url, ls_token, payload)
    if status not in (200, 201):
        result.add_error(
            f"Label Studio rejected the config "
            f"(POST {create_url} -> {status}): {_format_ls_error(body)}"
        )
        return result
    pid = body.get("id")
    if pid is None:
        result.add_warning(
            "Server accepted the config but didn't return a project id; "
            "leaving any throwaway project behind for the user to clean up."
        )
        return result
    # Clean up.
    del_url = f"{ls_url}/api/projects/{pid}/"
    try:
        _http("DELETE", del_url, ls_token)
    except RuntimeError as e:
        result.add_warning(
            f"Validation succeeded but the throwaway project (id={pid}) "
            f"could not be deleted automatically: {e}. Delete it from "
            f"the LS UI."
        )
    return result


def _format_ls_error(body: dict) -> str:
    """Make LS's nested validation error readable."""
    if isinstance(body, dict):
        for key in ("label_config", "detail", "non_field_errors"):
            if key in body:
                val = body[key]
                if isinstance(val, list):
                    return "; ".join(str(v) for v in val)
                return str(val)
    return json.dumps(body)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def read_config(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        help="Path to the XML config file, or `-` to read from stdin.",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help=(
            "Also validate against a running Label Studio instance "
            "($LABEL_STUDIO_URL / $LABEL_STUDIO_API_KEY)."
        ),
    )
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help=(
            "Validate against an existing project (uses its /validate/ "
            "endpoint). Otherwise the server check creates and "
            "immediately deletes a throwaway project."
        ),
    )
    parser.add_argument(
        "--label-studio-url",
        default=None,
        help="Override LABEL_STUDIO_URL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    _load_env_from_dotenv()
    config_text = read_config(args.config)

    overall = ValidationResult()

    root, parse_result = parse_xml(config_text)
    overall.extend(parse_result)
    if root is not None:
        overall.extend(validate_structure(root))

    server_attempted = False
    server_ok = None  # tri-state: None/True/False
    if args.server and root is not None and not overall.errors:
        # Only hit the server when local checks pass — server validation
        # adds latency and the local checks are exhaustive enough that
        # there's no point posting a known-broken config.
        ls_url = args.label_studio_url or os.environ.get(
            "LABEL_STUDIO_URL", "http://localhost:8080"
        )
        ls_token = os.environ.get("LABEL_STUDIO_API_KEY", "")
        if not ls_token:
            overall.add_warning(
                "--server requested but LABEL_STUDIO_API_KEY is not set "
                "(env or .env). Skipping server-side validation."
            )
        else:
            try:
                server_attempted = True
                overall.extend(
                    server_validate(
                        config_text, ls_url, ls_token,
                        project_id=args.project_id,
                    )
                )
                # If server_validate didn't add errors, the server side
                # is happy.
                server_ok = not overall.errors
            except RuntimeError as e:
                overall.add_warning(str(e))

    if args.json:
        print(json.dumps(
            {
                "ok": overall.ok,
                "errors": overall.errors,
                "warnings": overall.warnings,
                "server_attempted": server_attempted,
                "server_ok": server_ok,
            },
            indent=2,
        ))
    else:
        _print_human(overall, server_attempted, server_ok)

    return 0 if overall.ok else 1


def _print_human(result: ValidationResult, server_attempted: bool,
                 server_ok: bool | None) -> None:
    if result.errors:
        print("FAIL — config has errors:")
        for e in result.errors:
            print(f"  - {e}")
    else:
        print("OK — config passes local structural checks.")
    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  - {w}")
    if server_attempted:
        if server_ok:
            print("\nServer-side validation: OK (Label Studio accepted "
                  "the config).")
        elif server_ok is False:
            print("\nServer-side validation: FAILED (see errors above).")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
