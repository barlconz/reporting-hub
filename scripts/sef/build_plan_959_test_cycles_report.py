#!/usr/bin/env python3
"""Rebuild the SEF Plan 959 test-cycle report data from live Jira.

Scope rule:
- Direct children of PDE-4249
- issueType in ("Pre Requisite", "Test Cycle", "Test Cycle Level 0", "Gate Level 1")
- Exclude Regression cycle (PDE-4873)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PARENT_KEY = "PDE-4249"
EXCLUDED_KEYS = {"PDE-4873"}

REPORT_DOCS = Path("docs/sef/plans/sef-plan-959-test-cycles-only-excluding-prt-regression.html")
REPORT_MIRROR = Path("reports/sef/sef-plan-959-test-cycles-only-excluding-prt-regression.html")

CATEGORY_ORDER = [
    "pre requisite",
    "data migration testing",
    "non integrated parallel",
    "connectivity testing",
    "integration testing",
    "system integration testing",
    "end to end testing",
    "performance testing",
    "security testing",
    "user acceptance testing",
    "production verification testing",
    "dress rehearsal testing",
    "parallel run testing",
]

STATIC_DUAL_STRIP = {
    "PDE-4601": ["connectivity testing", "system integration testing"],
    "PDE-4727": ["connectivity testing", "end to end testing"],
    "PDE-4730": ["connectivity testing", "parallel run testing"],
    "PDE-4683": ["pre requisite", "non integrated parallel"],
    "PDE-4678": ["pre requisite", "system integration testing"],
    "PDE-4606": ["pre requisite", "end to end testing"],
    "PDE-4607": ["pre requisite", "user acceptance testing"],
    "PDE-4734": ["pre requisite", "parallel run testing"],
}

STATIC_CATEGORY_BY_KEY = {
    "PDE-4775": "system integration testing",  # System Integration Testing | Entry Gate
    "PDE-4773": "end to end testing",          # End to End Testing | Entry Gate
    "PDE-4780": "user acceptance testing",     # UAT Test Gate
    "PDE-4613": "parallel run testing",        # Go/No Go
    "PDE-4615": "parallel run testing",        # Go Live
    "PDE-4781": "parallel run testing",        # Parallel Test Gate
    "PDE-4778": "parallel run testing",        # Test Stage Gate
    "PDE-4783": "parallel run testing",        # Parallel Test Gate
}

# Temporary schedule fallback for scoped cycles that are approved but not yet dated in Jira.
# Remove once source issues have explicit start/end dates.
STATIC_DATE_FALLBACK_BY_KEY: dict[str, tuple[str, str]] = {
    "PDE-4984": ("2027-01-15", "2027-02-19"),  # Dress Rehearsal (aligned to PDE-4611 window)
}


def _load_credentials() -> tuple[str, str]:
    cred_path = os.environ.get("ARTIFACT_LOCAL_CREDENTIALS")
    if not cred_path:
        raise RuntimeError("ARTIFACT_LOCAL_CREDENTIALS is not set")
    raw = json.loads(Path(cred_path).read_text(encoding="utf-8"))
    client = raw["client-atlassian"]
    base = client["atlassian_base_url"].rstrip("/")
    user = client.get("email") or client.get("username")
    token = client["api_token"]
    auth = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("utf-8")
    return base, auth


def _post_json(base: str, auth: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(base: str, auth: str, path: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{base}{path}",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _pick_field_id(field_items: list[dict[str, Any]], name: str, preferred: str | None = None) -> str | None:
    ids = [f.get("id") for f in field_items if (f.get("name") or "").strip().lower() == name.lower()]
    if preferred and preferred in ids:
        return preferred
    return ids[0] if ids else None


def _adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(x) for x in node)
    if not isinstance(node, dict):
        return ""
    ntype = node.get("type")
    content = node.get("content") or []
    if ntype == "text":
        return str(node.get("text") or "")
    if ntype == "hardBreak":
        return "\n"
    if ntype in {"paragraph", "heading"}:
        text = "".join(_adf_to_text(x) for x in content).strip()
        return f"{text}\n\n" if text else ""
    return "".join(_adf_to_text(x) for x in content)


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_normalize_value(x) for x in value]
        return ", ".join([p for p in parts if p])
    if isinstance(value, dict):
        for key in ("value", "name", "displayName"):
            val = value.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""
    return ""


def _classify_category(key: str, issue_type: str, summary: str, test_type: str = "") -> str:
    if key in STATIC_CATEGORY_BY_KEY:
        return STATIC_CATEGORY_BY_KEY[key]

    if issue_type.strip().lower() == "pre requisite":
        return "pre requisite"

    s = summary.lower().strip()
    tt = test_type.lower().strip()
    haystack = f"{s} | {tt}"
    if "data migration testing" in haystack:
        return "data migration testing"
    if "uat" in s or "user acceptance" in s:
        return "user acceptance testing"
    if "non integrated parallel" in s:
        return "non integrated parallel"
    if "non integrated parallel" in tt:
        return "non integrated parallel"
    if "non integrated" in haystack and "parallel" in haystack:
        return "non integrated parallel"
    if "user acceptance testing" in s:
        return "user acceptance testing"
    if "production verification" in haystack:
        return "production verification testing"
    if "dress rehearsal" in haystack:
        return "dress rehearsal testing"
    if "parallel run" in s:
        return "parallel run testing"
    # Jira summaries often use "Testing | Parallel | ..." without "parallel run" text.
    if "parallel" in haystack:
        return "parallel run testing"
    if tt == "integration":
        return "integration testing"
    if "connectivity testing" in s:
        return "connectivity testing"
    # Keep SIT distinct. Only classify explicit integration test phases as Integration Testing.
    if s == "integration testing" or "| integration testing" in s:
        return "integration testing"
    if "system integration testing" in s or "system integration" in s:
        return "system integration testing"
    if "performance testing" in s:
        return "performance testing"
    if "penetration testing" in s or "security testing" in s:
        return "security testing"
    if "end to end" in s or "stabilization" in s:
        return "end to end testing"
    return "system integration testing"


def _replace_const_block(text: str, name: str, open_char: str, close_char: str, replacement_body: str) -> str:
    pattern = re.compile(
        rf"const\s+{re.escape(name)}\s*=\s*\{open_char}[\s\S]*?\{close_char};",
        re.MULTILINE,
    )
    replacement = f"const {name} = {open_char}\n{replacement_body}\n    {close_char};"
    # Use a callable replacement so backslash escapes in JSON (for example "\\n")
    # are preserved verbatim and not interpreted by re.sub.
    new_text, count = pattern.subn(lambda _m: replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not replace const block: {name}")
    return new_text


def _replace_string_const(text: str, name: str, value: str) -> str:
    pattern = re.compile(rf'const\s+{re.escape(name)}\s*=\s*"[^"]*";')
    replacement = f'const {name} = "{value}";'
    new_text, count = pattern.subn(lambda _m: replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not replace string const: {name}")
    return new_text


def _escape_js_string(value: str) -> str:
    # Keep inline JS valid even when Jira fields include control characters.
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    # Prevent HTML parser from terminating the script block on embedded </script>.
    return escaped.replace("</", "<\\/")


def _validate_template_integrity(text: str, source_name: str) -> None:
    if "<<<<<<< " in text or "=======" in text or ">>>>>>> " in text:
        raise RuntimeError(
            f"Template contains unresolved merge conflict markers: {source_name}. "
            "Resolve markers before running report generation."
        )
    if "<body>" not in text or '<div class="wrap"><div class="card">' not in text:
        raise RuntimeError(
            f"Template appears structurally incomplete: {source_name}. "
            "Expected body wrapper elements are missing."
        )


def _format_tasks(tasks: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for task in tasks:
        parts = [
            f'key: "{task["key"]}"',
            f'title: "{_escape_js_string(task["title"])}"',
            f'start: "{task["start"]}"',
            f'end: "{task["end"]}"',
            f'issueType: "{_escape_js_string(task.get("issueType", ""))}"',
            f'testType: "{_escape_js_string(task.get("testType", ""))}"',
            f'category: "{task["category"]}"',
        ]
        if task.get("parent"):
            parts.append(f'parent: "{task["parent"]}"')
        lines.append(f"      {{ {', '.join(parts)} }},")
    if lines:
        lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines)


def _format_object_array(items: list[dict[str, Any]], indent: str = "      ") -> str:
    if not items:
        return ""
    lines: list[str] = []
    for item in items:
        item_json = json.dumps(item, ensure_ascii=True).replace("</", "<\\/")
        lines.append(f"{indent}{item_json},")
    lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines)


def _format_object_map(data: dict[str, Any], indent: str = "    ") -> str:
    if not data:
        return ""
    lines: list[str] = []
    for key in sorted(data):
        value_json = json.dumps(data[key], ensure_ascii=True).replace("</", "<\\/")
        lines.append(f'{indent}"{key}": {value_json},')
    lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines)


def _build_issue_type_icon_map(issues: list[dict[str, Any]]) -> dict[str, str]:
    icon_map: dict[str, str] = {}
    for issue in issues:
        fields = issue.get("fields") or {}
        issue_type = fields.get("issuetype") or {}
        name = str(issue_type.get("name") or "").strip()
        icon_url = str(issue_type.get("iconUrl") or "").strip()
        if name and icon_url and name not in icon_map:
            icon_map[name] = icon_url
    return dict(sorted(icon_map.items()))


def _order_tasks_parent_first(tasks: list[dict[str, str]]) -> list[dict[str, str]]:
    category_rank = {name: idx for idx, name in enumerate(CATEGORY_ORDER)}

    def _sort_key(task: dict[str, str]) -> tuple[str, int, str]:
        return (
            str(task.get("start") or ""),
            category_rank.get(str(task.get("category") or ""), 999),
            str(task.get("key") or ""),
        )

    task_by_key = {t["key"]: t for t in tasks}
    children_by_parent: dict[str, list[dict[str, str]]] = {}
    for task in tasks:
      parent_key = task.get("parent")
      if parent_key:
          children_by_parent.setdefault(parent_key, []).append(task)

    for parent_key in list(children_by_parent):
        children_by_parent[parent_key].sort(key=_sort_key)

    ordered: list[dict[str, str]] = []
    seen: set[str] = set()

    def visit(task: dict[str, str]) -> None:
        key = task["key"]
        if key in seen:
            return
        seen.add(key)
        ordered.append(task)
        for child in children_by_parent.get(key, []):
            visit(child)

    roots = [
        task for task in tasks
        if not task.get("parent") or task.get("parent") not in task_by_key
    ]
    roots.sort(key=_sort_key)

    for task in roots:
        parent_key = task.get("parent")
        if not parent_key or parent_key not in task_by_key:
            visit(task)

    for task in tasks:
        visit(task)

    return ordered


def _is_blocks_link(link: dict[str, Any]) -> bool:
    link_type = link.get("type") or {}
    name = str(link_type.get("name") or "").strip().lower()
    inward = str(link_type.get("inward") or "").strip().lower()
    outward = str(link_type.get("outward") or "").strip().lower()
    if name == "blocks":
        return True
    return "block" in inward or "block" in outward


def _derive_dependencies_from_links(issues: list[dict[str, Any]], keys_in_scope: set[str]) -> list[dict[str, str]]:
    edges: set[tuple[str, str]] = set()
    for issue in issues:
        source_key = str(issue.get("key") or "").strip()
        if not source_key or source_key not in keys_in_scope:
            continue
        fields = issue.get("fields") or {}
        for link in fields.get("issuelinks") or []:
            if not _is_blocks_link(link):
                continue

            outward_issue = link.get("outwardIssue") or {}
            outward_key = str(outward_issue.get("key") or "").strip()
            if outward_key and outward_key in keys_in_scope:
                edges.add((source_key, outward_key))

            inward_issue = link.get("inwardIssue") or {}
            inward_key = str(inward_issue.get("key") or "").strip()
            if inward_key and inward_key in keys_in_scope:
                edges.add((inward_key, source_key))

    return [
        {"from": from_key, "to": to_key, "kind": "precursor"}
        for from_key, to_key in sorted(edges)
        if from_key != to_key
    ]


def _derive_dual_strip(tasks: list[dict[str, str]], dependencies: list[dict[str, str]]) -> dict[str, list[str]]:
    category_by_key = {t["key"]: t["category"] for t in tasks}
    derived: dict[str, list[str]] = {}

    for dep in dependencies:
        from_key = dep["from"]
        to_key = dep["to"]
        from_category = category_by_key.get(from_key)
        to_category = category_by_key.get(to_key)
        if not from_category or not to_category or from_category == to_category:
            continue
        derived[from_key] = [from_category, to_category]

    # Preserve manual overrides where they still apply.
    for key, strips in STATIC_DUAL_STRIP.items():
        if key in category_by_key:
            derived[key] = strips

    return dict(sorted(derived.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Plan 959 test cycle report data from Jira")
    parser.add_argument("--write-mirror", action="store_true", help="Also write reports/sef mirror HTML")
    args = parser.parse_args()

    base, auth = _load_credentials()

    fields = _get_json(base, auth, "/rest/api/3/field")
    field_items = fields if isinstance(fields, list) else []

    field_ids = {
        "platforms": _pick_field_id(field_items, "Platforms"),
        "tenant": _pick_field_id(field_items, "Tenant"),
        "tenant_name": _pick_field_id(field_items, "Tenant Name"),
        "test_company": _pick_field_id(field_items, "Test Company"),
        "test_types": _pick_field_id(field_items, "Test Types"),
        "ais_instance": _pick_field_id(field_items, "AIS Instance"),
        "elapsed_days": _pick_field_id(field_items, "Elapsed Days"),
        "work_days": _pick_field_id(field_items, "Work Days"),
        "weeks": _pick_field_id(field_items, "Weeks", preferred="customfield_14701"),
    }

    jira_fields = [
        "summary",
        "issuetype",
        "customfield_10015",
        "duedate",
        "description",
        "environment",
        "issuelinks",
        "parent",
    ] + [v for v in field_ids.values() if v]

    jql = (
        'parent = PDE-4249 AND issuetype in ("Pre Requisite", "Test Cycle", "Test Cycle Level 0", "Gate Level 1") '
        "AND key not in (PDE-4873) ORDER BY customfield_10015, key"
    )
    payload = _post_json(
        base,
        auth,
        "/rest/api/3/search/jql",
        {
            "jql": jql,
            "maxResults": 300,
            "fields": jira_fields,
        },
    )

    base_issues = payload.get("issues") or []

    # Pull one level of Jira children for all direct scoped issues so chart grouping can expand/collapse.
    base_keys = [str(i.get("key") or "").strip() for i in base_issues if i.get("key")]
    child_issues: list[dict[str, Any]] = []
    if base_keys:
        parent_list = ", ".join(base_keys)
        child_jql = f"parent in ({parent_list}) AND key not in (PDE-4873) ORDER BY parent, customfield_10015, key"
        child_payload = _post_json(
            base,
            auth,
            "/rest/api/3/search/jql",
            {
                "jql": child_jql,
                "maxResults": 500,
                "fields": jira_fields,
            },
        )
        child_issues = child_payload.get("issues") or []

    issue_by_key: dict[str, dict[str, Any]] = {}
    for issue in [*base_issues, *child_issues]:
        key = str(issue.get("key") or "").strip()
        if key:
            issue_by_key[key] = issue
    issues = list(issue_by_key.values())

    tasks: list[dict[str, str]] = []
    descriptions: dict[str, str] = {}
    metadata: dict[str, dict[str, str]] = {}
    metrics: dict[str, dict[str, str]] = {}

    for issue in issues:
        key = issue.get("key")
        if not key or key in EXCLUDED_KEYS:
            continue
        f = issue.get("fields") or {}
        start = f.get("customfield_10015")
        end = f.get("duedate")
        if (not start or not end) and key in STATIC_DATE_FALLBACK_BY_KEY:
            start, end = STATIC_DATE_FALLBACK_BY_KEY[key]
        if not start or not end:
            # Skip unscheduled rows to keep chart render stable.
            continue

        summary = str(f.get("summary") or "").strip()
        issue_type = str((f.get("issuetype") or {}).get("name") or "").strip()
        test_type = _normalize_value(f.get(field_ids["test_types"])) if field_ids["test_types"] else ""
        category = _classify_category(key, issue_type, summary, test_type)
        if category not in CATEGORY_ORDER:
            category = "system integration testing"

        task_row: dict[str, str] = {
            "key": key,
            "title": summary,
            "start": str(start),
            "end": str(end),
            "issueType": issue_type,
            "testType": test_type,
            "category": category,
        }
        parent_key = str(((f.get("parent") or {}).get("key")) or "").strip()
        if parent_key:
            task_row["parent"] = parent_key
        tasks.append(task_row)

        descriptions[key] = _adf_to_text(f.get("description")).strip()

        environment_val = _normalize_value(f.get("environment"))
        metadata[key] = {
            "Environment": environment_val,
            "Platforms": _normalize_value(f.get(field_ids["platforms"])) if field_ids["platforms"] else "",
            "Tenant": _normalize_value(f.get(field_ids["tenant"])) if field_ids["tenant"] else "",
            "Tenant Name": _normalize_value(f.get(field_ids["tenant_name"])) if field_ids["tenant_name"] else "",
            "Test Company": _normalize_value(f.get(field_ids["test_company"])) if field_ids["test_company"] else "",
            "AIS Instance": _normalize_value(f.get(field_ids["ais_instance"])) if field_ids["ais_instance"] else "",
        }

        elapsed = _normalize_value(f.get(field_ids["elapsed_days"])) if field_ids["elapsed_days"] else ""
        work = _normalize_value(f.get(field_ids["work_days"])) if field_ids["work_days"] else ""
        weeks = _normalize_value(f.get(field_ids["weeks"])) if field_ids["weeks"] else ""
        if elapsed or work or weeks:
            metrics[key] = {
                "Elapsed Days": elapsed,
                "Work Days": work,
                "Weeks": weeks,
            }

    tasks = _order_tasks_parent_first(tasks)
    issue_type_icons = _build_issue_type_icon_map(issues)

    keys_in_scope = {t["key"] for t in tasks}
    dependencies = _derive_dependencies_from_links(issues, keys_in_scope)
    dual_strip = _derive_dual_strip(tasks, dependencies)

    template = REPORT_DOCS.read_text(encoding="utf-8")
    _validate_template_integrity(template, str(REPORT_DOCS))
    template = _replace_const_block(template, "TASKS", "[", "]", _format_tasks(tasks))
    template = _replace_const_block(template, "ISSUE_TYPE_ICONS", "{", "}", _format_object_map(issue_type_icons))
    template = _replace_const_block(template, "DUAL_STRIP_BY_KEY", "{", "}", _format_object_map(dual_strip))
    template = _replace_const_block(template, "DEPENDENCIES", "[", "]", _format_object_array(dependencies))
    template = _replace_const_block(template, "ISSUE_DESCRIPTIONS", "{", "}", _format_object_map(descriptions))
    template = _replace_const_block(template, "ISSUE_METADATA", "{", "}", _format_object_map(metadata))
    template = _replace_const_block(template, "ISSUE_METRICS", "{", "}", _format_object_map(metrics))
    # Always render the report timestamp in New Zealand local time for stakeholder readability.
    rendered_at = datetime.now(ZoneInfo("Pacific/Auckland")).strftime("%Y-%m-%d %H:%M:%S") + " NZT"
    template = _replace_string_const(template, "RENDERED_AT", rendered_at)

    REPORT_DOCS.write_text(template, encoding="utf-8")
    print(f"Wrote {REPORT_DOCS} ({len(tasks)} scoped items)")

    if args.write_mirror:
        REPORT_MIRROR.parent.mkdir(parents=True, exist_ok=True)
        REPORT_MIRROR.write_text(template, encoding="utf-8")
        print(f"Wrote {REPORT_MIRROR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
