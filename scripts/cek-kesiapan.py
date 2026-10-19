"""Pemeriksaan kesiapan lokal sebelum menjalankan aplikasi.

Masalah yang dicegah: `backend/.env` yang hilang membuat semua login dijawab
401, walaupun passcode yang diketik benar. Gejalanya sangat mudah
disalahartikan sebagai bug aplikasi, karena halaman login tetap tampil normal
dan tidak ada pesan yang menyebut konfigurasi.

Skrip ini memeriksa hal-hal yang paling sering salah di setup lokal, dan
menjelaskan tindakannya. Aman dijalankan berkali-kali, dan tidak mengubah apa
pun tanpa memberi tahu.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
BACKEND = AKAR / "backend"
FRONTEND = AKAR / "frontend"

masalah: list[str] = []
saran: list[str] = []


def periksa(judul: str, benar: bool, pesan: str) -> None:
    tanda = "OK   " if benar else "MASALAH"
    print(f"[{tanda}] {judul}")
    if not benar:
        masalah.append(judul)
        saran.append(pesan)


print("== Konfigurasi backend")
env = BACKEND / ".env"
periksa(
    "backend/.env ada",
    env.exists(),
    "Jalankan: Copy-Item backend/.env.example backend/.env, lalu isi "
    "ACCESS_PASSCODE_SHA256.",
)

isi_env = env.read_text(encoding="utf-8") if env.exists() else ""

cocok = re.search(r"^ACCESS_PASSCODE_SHA256=(.*)$", isi_env, re.M)
nilai = cocok.group(1).strip() if cocok else ""
periksa(
    "ACCESS_PASSCODE_SHA256 terisi",
    len(nilai) == 64,
    "Tanpa nilai ini SEMUA login ditolak 401. Buat dengan: "
    "cd backend && python -m scripts.make_passcode",
)

print()
print("== Konfigurasi frontend")
envl = FRONTEND / ".env.local"
if envl.exists():
    isi_envl = envl.read_text(encoding="utf-8")
    pakai_backend = re.search(r"^NEXT_PUBLIC_USE_BACKEND=(.*)$", isi_envl, re.M)
    nilai_ub = pakai_backend.group(1).strip() if pakai_backend else ""
    print(f"[INFO ] frontend/.env.local ada, NEXT_PUBLIC_USE_BACKEND={nilai_ub or '(kosong)'}")
    if nilai_ub in ("1", "true", "yes", "on"):
        print("         Artinya frontend memakai backend sungguhan.")
        print("         Backend HARUS berjalan, kalau tidak login akan gagal.")
    else:
        print("         Artinya mode demo: data dari browser, tanpa backend.")
else:
    print("[INFO ] frontend/.env.local tidak ada: mode demo (tanpa backend)")

print()
print("== Ringkasan")
if masalah:
    print(f"{len(masalah)} masalah ditemukan:")
    for i, (m, s) in enumerate(zip(masalah, saran, strict=True), 1):
        print(f"  {i}. {m}")
        print(f"     Tindakan: {s}")
    sys.exit(1)

print("Semua pemeriksaan lulus. Aplikasi siap dijalankan:")
print("  Terminal 1: cd backend  && python -m uvicorn app.main:app --port 8000")
print("  Terminal 2: cd frontend && npm run dev")
print("  Buka       : http://localhost:3000")
