"""CSV and Excel export helpers. (Excel requires: pip install moodlectl[export])"""
from __future__ import annotations

import csv
import pathlib


def to_csv(data: list[dict], columns: list[str], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
    print(f"Saved: {pathlib.Path(path).resolve()}")


def to_excel(data: list[dict], columns: list[str], path: str) -> None:
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("Excel export requires: pip install moodlectl[export]")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(columns)
    for row in data:
        ws.append([row.get(c, "") for c in columns])
    wb.save(path)
    print(f"Saved: {pathlib.Path(path).resolve()}")
