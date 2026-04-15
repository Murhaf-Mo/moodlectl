"""CSV and Excel export helpers. (Excel requires: pip install moodlectl[export])"""
from __future__ import annotations

import csv
import pathlib
from collections.abc import Mapping, Sequence


def to_csv(data: Sequence[Mapping[str, object]], columns: list[str], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in data:
            writer.writerow([str(row.get(c, "")) for c in columns])
    print(f"Saved: {pathlib.Path(path).resolve()}")


def to_excel(data: Sequence[Mapping[str, object]], columns: list[str], path: str) -> None:
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("Excel export requires: pip install moodlectl[export]")

    wb = openpyxl.Workbook()
    ws = wb.active
    if ws is None:
        raise RuntimeError("openpyxl could not create a worksheet")
    ws.append(columns)
    for row in data:
        ws.append([str(row.get(c, "")) for c in columns])
    wb.save(path)
    print(f"Saved: {pathlib.Path(path).resolve()}")
