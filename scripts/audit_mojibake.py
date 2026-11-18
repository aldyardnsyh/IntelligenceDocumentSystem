"""Pindai mojibake & karakter mencurigakan di kode + dokumentasi repo.

Dipakai dari akar repo:
    python scripts/audit_mojibake.py

Laporan keluar membantu pembersihan; file data eksternal (ids_upgrade,
gold JSON) dan node_modules sengaja dilewati.
"""

from __future__ import annotations

import pathlib
import re

# Pola mojibake khas UTF-8 salah dekode (cp1252/latin-1) + replacement char.
# Ditulis dengan escape supaya tidak bergantung pada tanda kutip pintar.
# Em dash (E2 80 94) dan en dash (E2 80 93) yang salah dekode cp1252 adalah
# kasus paling sering pada teks Indonesia: urutan a-circumflex + tanda euro
# nyaris mustahil muncul dalam tulisan yang sah.
MOJIBAKE = re.compile(
    r"(\u00e2\u20ac"
    r"|\u00c3[\u00a9\u00ab\u00bb\u0080-\u00bf\w]"
    r"|\u00c2[\u00a0-\u00bf]"
    r"|\u00ef\u00bb\u00bf"
    r"|\u00ef\u00bf\u00bd"
    r"|\ufffd)"
)

SUSPICIOUS = {
    "\u202f": "narrow nbsp",
    "\u2009": "thin space",
    "\ufeff": "BOM/ZWNBSP",
    "\u00ad": "soft hyphen",
    "\u2028": "line separator",
    "\u2029": "paragraph separator",
}

SKIPPED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".next",
    "test-results", "playwright-report", ".turbo", "ids_upgrade",
}
# File vendor hasil build pihak ketiga tidak pernah diedit tangan.
EXCLUDED_FILES = {"perpres_76_2013.json", "pdf.worker.min.mjs"}
# File yang sengaja MEMUAT karakter terlarang di teksnya (komentar yang
# membahas karakter itu sendiri) — bukan mojibake.
DOC_EXCEPTIONS = {
    "backend/app/services/ingestion/parser.py": {"BOM/ZWNBSP"},
}
EXTS = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".css",
        ".toml", ".yml", ".yaml", ".sh", ".txt", ".html"}


def scan(root: pathlib.Path) -> dict[str, list[tuple[str, str]]]:
    findings: dict[str, list[tuple[str, str]]] = {}
    for path in root.rglob("*"):
        if path.is_dir() or any(part in SKIPPED_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDED_FILES or path.suffix.lower() not in EXTS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, PermissionError, OSError):
            findings.setdefault("<tidak-bisa-dibaca-utf8>", []).append(
                (str(path), "")
            )
            continue
        hits: list[tuple[str, str]] = []
        exceptions = DOC_EXCEPTIONS.get(str(path.relative_to(root)).replace("\\", "/"), set())
        for match in MOJIBAKE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            hits.append(("MOJIBAKE", f"baris {line}: {match.group(0)!r}"))
        for char, label in SUSPICIOUS.items():
            if label in exceptions:
                continue
            count = text.count(char)
            if count:
                hits.append((label, f"{count}x"))
        if hits:
            findings[str(path)] = hits
    return findings


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    findings = scan(root)
    if not findings:
        print("BERSIH: tidak ada mojibake / karakter mencurigakan")
        return 0
    for path, hits in findings.items():
        print(f"== {path}")
        for label, detail in hits[:8]:
            print(f"   {label}: {detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
