#!/usr/bin/env python3
"""Ensure quarantined price histories never affect dashboard decision metrics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CURRENT = ROOT / "data" / "current.json"
DASHBOARD = ROOT / "data" / "dashboard.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [record for record in value.values() if isinstance(record, dict)]
    if isinstance(value, list):
        return [record for record in value if isinstance(record, dict)]
    return []


def clear_quarantined(records: list[dict[str, Any]]) -> int:
    changed = 0
    for record in records:
        status = str(record.get("price_change_status") or "")
        if not status.startswith("quarantined"):
            continue
        if int(record.get("price_change_yen_validated") or 0) != 0:
            record["price_change_yen_validated"] = 0
            changed += 1
    return changed


def main() -> None:
    current = load(CURRENT)
    current_changed = clear_quarantined(rows(current.get("listings")))
    save(CURRENT, current)

    dashboard = load(DASHBOARD)
    dashboard_changed = clear_quarantined(rows(dashboard.get("listings")))
    save(DASHBOARD, dashboard)

    print(json.dumps({
        "current_quarantined_metrics_cleared": current_changed,
        "dashboard_quarantined_metrics_cleared": dashboard_changed,
    }))


if __name__ == "__main__":
    main()
