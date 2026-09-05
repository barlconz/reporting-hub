#!/usr/bin/env python3
"""Generate a governance summary for GitHub Copilot billing.

Outputs the four requested controls:
1) Total per month
2) Breakout per group (EPC, TWoA)
3) New additions since last run
4) Removed users since last run
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports" / "github-billing"
DOCS_DATA_DIR = ROOT / "docs" / "enterprise" / "data"
CONFIG_PATH = ROOT / "config" / "github-copilot-governance-groups.json"
DOCS_OUTPUT = ROOT / "docs" / "enterprise" / "github-copilot-governance.html"
SUMMARY_JSON = DOCS_DATA_DIR / "governance-summary-latest.json"
STATE_PATH = DOCS_DATA_DIR / "governance-last-members.json"


@dataclass
class UserRow:
    login: str
    resolved_name: str
    has_copilot_seat: bool
    estimated_gross_usd: float


@dataclass
class GovernanceConfig:
    groups: dict[str, set[str]]
    currency_display: str
    usd_to_nzd_rate: float


def _latest_file(pattern: str) -> Path | None:
    candidates = sorted(REPORTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_config() -> GovernanceConfig:
    if not CONFIG_PATH.exists():
        return GovernanceConfig(groups={"EPC": set(), "TWoA": set()}, currency_display="NZD", usd_to_nzd_rate=1.65)

    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    groups = payload.get("groups", {})
    currency = payload.get("currency", {})
    return GovernanceConfig(
        groups={name: set(logins) for name, logins in groups.items()},
        currency_display=str(currency.get("display") or "NZD"),
        usd_to_nzd_rate=float(currency.get("usdToNzdRate") or 1.65),
    )


def _load_users(csv_path: Path) -> list[UserRow]:
    rows: list[UserRow] = []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        estimate_col = None
        for field in reader.fieldnames or []:
            if field.endswith("_estimated_gross_usd"):
                estimate_col = field
                break
        if estimate_col is None:
            raise ValueError("Could not find estimated gross column in per-user CSV.")

        for row in reader:
            rows.append(
                UserRow(
                    login=(row.get("member_login") or "").strip(),
                    resolved_name=(row.get("resolved_name") or "").strip() or "Unknown",
                    has_copilot_seat=((row.get("has_copilot_seat") or "").strip().lower() == "yes"),
                    estimated_gross_usd=float((row.get(estimate_col) or "0").strip() or 0),
                )
            )
    return rows


def _load_monthly_total(usage_path: Path) -> dict[str, Any]:
    payload = json.loads(usage_path.read_text(encoding="utf-8"))
    items = payload.get("usageItems", [])
    by_month: dict[str, float] = {}
    for item in items:
        if (item.get("product") or "").lower() != "copilot":
            continue
        date = str(item.get("date") or "")
        month = date[:7]
        if len(month) != 7:
            continue
        by_month[month] = by_month.get(month, 0.0) + float(item.get("netAmount") or 0.0)

    if not by_month:
        return {"month": "unknown", "net_total_usd": 0.0}

    latest_month = sorted(by_month.keys())[-1]
    return {"month": latest_month, "net_total_usd": by_month[latest_month]}


def _load_seated_since(seats_path: Path | None) -> dict[str, str]:
    if seats_path is None or not seats_path.exists():
        return {}

    payload = json.loads(seats_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for seat in payload.get("seats", []):
        assignee = seat.get("assignee") or {}
        login = str(assignee.get("login") or "").strip()
        created_at = str(seat.get("created_at") or "").strip()
        if not login or not created_at:
            continue
        out[login] = created_at[:10]
    return out


def _load_last_used(seats_path: Path | None) -> dict[str, str]:
    if seats_path is None or not seats_path.exists():
        return {}

    payload = json.loads(seats_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for seat in payload.get("seats", []):
        assignee = seat.get("assignee") or {}
        login = str(assignee.get("login") or "").strip()
        last_used = str(seat.get("last_activity_at") or seat.get("last_authenticated_at") or "").strip()
        if not login or not last_used:
            continue
        out[login] = last_used[:10]
    return out


def _load_budget_controls(budgets_path: Path | None, usd_to_nzd_rate: float) -> dict[str, Any]:
    if budgets_path is None or not budgets_path.exists():
        return {"rows": [], "alert_recipients": set(), "org_enforced": False}

    payload = json.loads(budgets_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    recipients: set[str] = set()
    enforced = True

    for item in payload.get("budgets", []):
        alerting = item.get("budget_alerting") or {}
        budget_recipients = [str(x) for x in (alerting.get("alert_recipients") or [])]
        recipients.update(budget_recipients)
        prevent = bool(item.get("prevent_further_usage"))
        enforced = enforced and prevent
        usd_amount = float(item.get("budget_amount") or 0.0)
        rows.append(
            {
                "sku": str(item.get("budget_product_sku") or ""),
                "scope": str(item.get("budget_scope") or "organization"),
                "budget_nzd": usd_amount * usd_to_nzd_rate,
                "prevent_further_usage": prevent,
                "will_alert": bool(alerting.get("will_alert")),
                "recipients": sorted(budget_recipients),
            }
        )

    rows.sort(key=lambda r: r["sku"])
    return {"rows": rows, "alert_recipients": recipients, "org_enforced": enforced}


def _group_breakout(
    users: list[UserRow],
    groups: dict[str, set[str]],
    usd_to_nzd_rate: float,
    seated_since_map: dict[str, str],
    last_used_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    known_groups = ["EPC", "TWoA"]
    stats: dict[str, dict[str, Any]] = {
        group: {"group": group, "users": 0, "seated_users": 0, "estimated_gross_nzd": 0.0}
        for group in known_groups
    }
    unmapped: list[str] = []
    grouped_users: list[dict[str, Any]] = []

    for user in users:
        group_name = None
        for candidate in known_groups:
            if user.login in groups.get(candidate, set()):
                group_name = candidate
                break
        if group_name is None:
            unmapped.append(user.login)
            continue

        grouped_users.append(
            {
                "group": group_name,
                "login": user.login,
                "name": user.resolved_name,
                "has_copilot_seat": user.has_copilot_seat,
                "seated_since": seated_since_map.get(user.login),
                "last_used": last_used_map.get(user.login),
            }
        )

        bucket = stats[group_name]
        bucket["users"] += 1
        if user.has_copilot_seat:
            bucket["seated_users"] += 1
        bucket["estimated_gross_nzd"] += user.estimated_gross_usd * usd_to_nzd_rate

    ordered = [stats["EPC"], stats["TWoA"]]
    for row in ordered:
        seated = row["seated_users"]
        row["cost_per_user_nzd"] = (row["estimated_gross_nzd"] / seated) if seated else 0.0

    # Order by seated date, then group/name. Users without seats go to bottom.
    grouped_users.sort(
        key=lambda x: (
            x["seated_since"] is None,
            x["seated_since"] or "9999-12-31",
            x["group"],
            x["name"].lower(),
            x["login"].lower(),
        )
    )
    return ordered, sorted(unmapped), grouped_users


def _read_previous_members() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return set(payload.get("members", []))


def _write_member_state(current_members: set[str], previous_members: set[str]) -> None:
    if current_members == previous_members:
        return
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"members": sorted(current_members)}
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _render_html(summary: dict[str, Any]) -> str:
    monthly = summary["monthly"]
    groups = summary["groups"]
    grouped_users = summary["grouped_users"]
    additions = summary["additions"]
    removals = summary["removals"]
    unmapped = summary["unmapped"]
    currency = summary["currency"]
    billing = summary["billing"]

    def _rows() -> str:
        parts = []
        for row in groups:
            parts.append(
                "<tr>"
                f"<td><span class=\"group-tag\">{row['group']}</span></td>"
                f"<td class=\"num\">{row['users']}</td>"
                f"<td class=\"num\">{row['seated_users']}</td>"
                f"<td class=\"num\">{row['estimated_gross_nzd']:.2f}</td>"
                f"<td class=\"num\">{row['cost_per_user_nzd']:.2f}</td>"
                "</tr>"
            )
        return "".join(parts)

    def _user_rows() -> str:
        parts = []
        for row in grouped_users:
            seat_label = (
                "<span class=\"badge yes\">Seated</span>"
                if row["has_copilot_seat"]
                else "<span class=\"badge no\">Not Seated</span>"
            )
            seated_since = row["seated_since"] or "-"
            last_used = row["last_used"] or "-"
            row_class = " class=\"row-no-seat\"" if not row["has_copilot_seat"] else ""
            parts.append(
                f"<tr{row_class}>"
                f"<td><span class=\"group-tag\">{row['group']}</span></td>"
                f"<td>{row['name']}</td>"
                f"<td><span class=\"mono\">{row['login']}</span></td>"
                f"<td>{seated_since}</td>"
                f"<td>{last_used}</td>"
                f"<td>{seat_label}</td>"
                "</tr>"
            )
        return "".join(parts)

    def _list(items: list[str]) -> str:
        if not items:
            return "<li><span class=\"pill none\">None</span></li>"
        return "".join(f"<li><span class=\"pill\">{item}</span></li>" for item in items)

    def _billing_rows() -> str:
        parts = []
        for row in billing["rows"]:
            parts.append(
                "<tr>"
                f"<td>{row['sku']}</td>"
                f"<td class=\"num\">{row['budget_nzd']:.2f}</td>"
                "</tr>"
            )
        if not parts:
            return "<tr><td colspan=\"2\">No budget control data found.</td></tr>"
        return "".join(parts)

    budget_rows = billing.get("rows") or []
    scope_values = sorted({row.get("scope", "-") for row in budget_rows})
    prevent_values = sorted({row.get("prevent_further_usage") for row in budget_rows})
    alert_values = sorted({row.get("will_alert") for row in budget_rows})
    recipients_values = sorted(set(billing.get("alert_recipients") or []))
    scope_text = ", ".join(scope_values) if scope_values else "-"
    prevent_text = "Yes" if prevent_values == [True] else ("No" if prevent_values == [False] else "Mixed")
    alerts_text = "Yes" if alert_values == [True] else ("No" if alert_values == [False] else "Mixed")
    recipients_text = ", ".join(recipients_values) if recipients_values else "-"

    unmapped_note = ""
    if unmapped:
        joined = ", ".join(unmapped)
        unmapped_note = (
            "<p class=\"note warn\"><strong>Unmapped users:</strong> "
            f"{joined}. Add them to config/github-copilot-governance-groups.json.</p>"
        )

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>GitHub Copilot Governance Summary</title>
  <style>
    :root {{
      --bg:#f4f8fb;
      --bg-accent:#e6eff7;
      --card:#ffffff;
      --text:#0f2740;
      --muted:#5b6d7d;
      --border:#d6e1ea;
      --accent:#0b69a3;
      --accent-2:#0f8b6d;
      --warn:#9a6300;
      --shadow:0 10px 24px rgba(15,39,64,0.08);
    }}
    html,body {{
      margin:0;
      padding:0;
      background:
        radial-gradient(1200px 500px at 95% -10%, var(--bg-accent), transparent 70%),
        var(--bg);
      color:var(--text);
      font-family:"Segoe UI",Arial,sans-serif;
    }}
    .wrap {{ max-width:1080px; margin:30px auto; padding:0 18px 24px; }}
    .card {{
      background:var(--card);
      border:1px solid var(--border);
      border-radius:14px;
      padding:20px;
      margin-bottom:16px;
      box-shadow:var(--shadow);
    }}
    .hero {{
      background:linear-gradient(120deg, #0b69a3, #0f8b6d);
      color:#fff;
      border:0;
      box-shadow:0 14px 30px rgba(11,105,163,0.25);
    }}
    h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0.2px; }}
    h2 {{ margin:0 0 12px; font-size:21px; }}
    h3 {{ margin:18px 0 10px; font-size:16px; color:#12395b; }}
    p.meta {{ margin:0; color:var(--muted); }}
    .hero p.meta {{ color:#e9f5ff; }}
    .kpi {{ font-size:36px; font-weight:700; margin:6px 0 0; color:var(--accent-2); }}
    table {{ width:100%; border-collapse:separate; border-spacing:0; font-size:14px; overflow:hidden; border-radius:10px; }}
    th,td {{ border:1px solid var(--border); border-left:0; border-top:0; padding:9px 11px; text-align:left; background:#fff; }}
    th:first-child, td:first-child {{ border-left:1px solid var(--border); }}
    thead th {{ background:#edf4fa; font-weight:600; color:#12395b; }}
    tbody tr:nth-child(even) td {{ background:#fbfdff; }}
    tbody tr.row-no-seat td {{ background:#fff6e8 !important; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .note {{ border-left:4px solid var(--accent); background:#f1f7fd; padding:10px 12px; border-radius:8px; }}
    .warn {{ border-left-color:var(--warn); }}
    .group-tag {{
      display:inline-block;
      font-weight:600;
      font-size:12px;
      padding:3px 8px;
      border-radius:999px;
      background:#eaf3fb;
      color:#0f4f7d;
    }}
    .badge {{
      display:inline-block;
      font-size:12px;
      font-weight:600;
      padding:3px 8px;
      border-radius:999px;
    }}
    .badge.yes {{ background:#e5f7f1; color:#0a6b53; }}
    .badge.no {{ background:#f7f2e6; color:#8a5a00; }}
    .mono {{ font-family:Consolas, "Courier New", monospace; font-size:13px; }}
    .pill {{
      display:inline-block;
      background:#eef5fb;
      border:1px solid #d6e6f3;
      color:#1f4b71;
      border-radius:999px;
      padding:4px 9px;
      font-size:12px;
      margin:2px 0;
    }}
    .pill.none {{ background:#f5f7f9; color:#5c6b78; border-color:#dde4ea; }}
    ul {{ margin:8px 0 0; padding-left:20px; }}
  </style>
</head>
<body>
<div class=\"wrap\">
  <div class=\"card hero\">
    <h1>GitHub Copilot Governance Summary</h1>
    <p class=\"meta\">Scope: monthly total, EPC/TWoA split, additions, removals.</p>
    <p class=\"meta\">Currency display: {currency}</p>
  </div>

  <div class=\"card\">
    <h2>Total Per Month</h2>
    <p class=\"meta\">Latest month in org usage feed</p>
    <p><strong>Month:</strong> {monthly['month']}</p>
    <p class=\"kpi\">{currency} {monthly['net_total_nzd']:.2f}</p>
  </div>

    <div class=\"card\">
        <h2>Billing Configuration, Limits and Alerts</h2>
        <p class=\"note\"><strong>Enforcement status:</strong> {'Enabled' if billing['org_enforced'] else 'Review needed'} (based on prevent_further_usage across configured budgets).</p>
        <h3>Organization Controls</h3>
        <p class=\"meta\"><strong>Scope:</strong> {scope_text} | <strong>Prevent Further Usage:</strong> {prevent_text} | <strong>Alerts Enabled:</strong> {alerts_text} | <strong>Alert Recipients:</strong> {recipients_text}</p>
        <table>
            <thead>
                <tr>
                    <th>SKU</th>
                    <th class=\"num\">Budget ({currency})</th>
                </tr>
            </thead>
            <tbody>{_billing_rows()}</tbody>
        </table>
    </div>

  <div class=\"card\">
    <h2>Breakout Per Group</h2>
    <table>
      <thead>
        <tr>
          <th>Group</th>
          <th class=\"num\">Users</th>
          <th class=\"num\">Seated Users</th>
          <th class=\"num\">Estimated Monthly Seat Cost ({currency})</th>
                    <th class=\"num\">Cost per Seated User ({currency})</th>
        </tr>
      </thead>
      <tbody>{_rows()}</tbody>
    </table>
    <p class=\"note\"><strong>Method:</strong> group split is from the latest per-user seat estimate file; values converted from USD using configured FX rate.</p>
    {unmapped_note}

    <h3>Users by Group (Full Names)</h3>
    <table>
      <thead>
        <tr>
          <th>Group</th>
          <th>Full Name</th>
          <th>User Login</th>
                    <th>Seated Since</th>
                                        <th>Last Used</th>
          <th>Has Copilot Seat</th>
        </tr>
      </thead>
      <tbody>{_user_rows()}</tbody>
    </table>
  </div>

  <div class=\"card\">
    <h2>New Additions Since Last Run</h2>
    <ul>{_list(additions)}</ul>
  </div>

  <div class=\"card\">
    <h2>Removed Since Last Run</h2>
    <ul>{_list(removals)}</ul>
  </div>
</div>
</body>
</html>
"""


def main() -> int:
    csv_path = _latest_file("per-user-billing-estimates-*.csv")
    usage_path = _latest_file("data/org-usage-*.json")
    if csv_path is None or usage_path is None:
        print("No billing source artifacts found in reports/github-billing; skipping governance summary.")
        return 0

    users = _load_users(csv_path)
    config = _load_config()
    monthly = _load_monthly_total(usage_path)
    seats_path = _latest_file("data/copilot-seats-*.json")
    budgets_path = _latest_file("data/org-budgets-*.json")
    seated_since_map = _load_seated_since(seats_path)
    last_used_map = _load_last_used(seats_path)
    grouped, unmapped, grouped_users = _group_breakout(
        users,
        config.groups,
        config.usd_to_nzd_rate,
        seated_since_map,
        last_used_map,
    )
    billing = _load_budget_controls(budgets_path, config.usd_to_nzd_rate)

    current_members = {u.login for u in users}
    previous_members = _read_previous_members()
    additions = sorted(current_members - previous_members)
    removals = sorted(previous_members - current_members)

    monthly_nzd = monthly["net_total_usd"] * config.usd_to_nzd_rate

    summary = {
        "sources": {
            "per_user_csv": str(csv_path.relative_to(ROOT)),
            "org_usage": str(usage_path.relative_to(ROOT)),
            "copilot_seats": str(seats_path.relative_to(ROOT)) if seats_path else None,
            "org_budgets": str(budgets_path.relative_to(ROOT)) if budgets_path else None,
        },
        "currency": config.currency_display,
        "usd_to_nzd_rate": config.usd_to_nzd_rate,
        "monthly": {
            "month": monthly["month"],
            "net_total_usd": monthly["net_total_usd"],
            "net_total_nzd": monthly_nzd,
        },
        "groups": grouped,
        "grouped_users": grouped_users,
        "billing": {
            "rows": billing["rows"],
            "alert_recipients": sorted(billing["alert_recipients"]),
            "org_enforced": billing["org_enforced"],
        },
        "additions": additions,
        "removals": removals,
        "unmapped": unmapped,
    }

    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    DOCS_OUTPUT.write_text(_render_html(summary), encoding="utf-8")

    _write_member_state(current_members, previous_members)

    print(f"Wrote summary JSON: {SUMMARY_JSON.relative_to(ROOT)}")
    print(f"Wrote summary HTML: {DOCS_OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
