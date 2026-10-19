"""Siapkan pemakaian lokal dengan satu perintah.

Ditulis untuk pengguna baru: satu perintah menyiapkan semuanya sampai aplikasi
bisa dijalankan, tanpa perlu tahu berkas mana yang harus disalin atau nilai apa
yang harus diisi.

Yang dikerjakan:

1. Membuat `backend/.env` dari `.env.example`, dengan passcode acak yang aman
   dan hash-nya dihitung memakai fungsi yang sama dengan yang dipakai backend.
2. Membuat `frontend/.env.local` dari `.env.example`.
3. Membuat folder data yang dibutuhkan.
4. Memeriksa perangkat yang dibutuhkan (Python, Node) dan memberi tahu versinya.
5. Memeriksa apakah dependency Python dan Node sudah terpasang, dan memberi
   perintah pemasangannya kalau belum.

Yang TIDAK dikerjakan, dan disengaja:

- Tidak menimpa berkas yang sudah ada. Rahasia yang sudah diisi tidak boleh
  hilang karena skrip dijalankan ulang.
- Tidak mengunduh model embedding.
- Tidak menyalakan server.

Passcode yang dibuat ditampilkan SEKALI, karena hanya hash-nya yang disimpan.
Kalau pengguna kehilangannya, ia bisa menjalankan skrip ini lagi setelah
menghapus `backend/.env`, atau memakai `python -m scripts.make_passcode`.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
import sys
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
BACKEND = AKAR / "backend"
FRONTEND = AKAR / "frontend"

# Huruf dan angka tanpa karakter yang mudah tertukar saat diketik ulang
# (0/O, 1/l/I). Passcode ini akan diketik manual di layar login.
ABJAD = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def passcode_acak(panjang: int = 16) -> str:
    """Passcode acak yang aman, tanpa karakter yang mudah tertukar."""
    return "".join(secrets.choice(ABJAD) for _ in range(panjang))


def hash_passcode(nilai: str) -> str:
    """Hitung hash memakai fungsi backend, supaya hasilnya pasti cocok.

    Kalau hashing ditulis ulang di sini, dua implementasi bisa berbeda dan
    login akan gagal tanpa pesan yang menjelaskan sebabnya.
    """
    sys.path.insert(0, str(BACKEND))
    from app.core.security import hash_passcode as milik_backend  # noqa: PLC0415

    return milik_backend(nilai)


def tulis_env_backend() -> tuple[bool, str | None]:
    """Buat backend/.env kalau belum ada. Kembalikan (dibuat, passcode)."""
    tujuan = BACKEND / ".env"
    if tujuan.exists():
        return False, None

    contoh = BACKEND / ".env.example"
    if not contoh.exists():
        raise SystemExit(f"GAGAL: {contoh} tidak ditemukan.")

    sandi = passcode_acak()
    digest = hash_passcode(sandi)

    baris: list[str] = []
    for isi in contoh.read_text(encoding="utf-8").splitlines():
        if isi.startswith("ACCESS_PASSCODE_SHA256="):
            baris.append(f"ACCESS_PASSCODE_SHA256={digest}")
        elif isi.startswith("LLM_PROVIDER="):
            # mock: tanpa API key dan tanpa biaya, cocok untuk mencoba.
            baris.append("LLM_PROVIDER=mock")
        elif isi.startswith("DEBUG="):
            baris.append("DEBUG=true")
        elif isi.startswith("API_DOCS_ENABLED="):
            # Berguna saat mencoba: /docs bisa dibuka di browser.
            baris.append("API_DOCS_ENABLED=1")
        elif isi.startswith("CORS_ORIGINS="):
            baris.append("CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000")
        else:
            baris.append(isi)

    tujuan.write_text("\n".join(baris) + "\n", encoding="utf-8")
    return True, sandi


def tulis_env_frontend() -> bool:
    """Buat frontend/.env.local kalau belum ada."""
    tujuan = FRONTEND / ".env.local"
    if tujuan.exists():
        return False

    contoh = FRONTEND / ".env.example"
    if not contoh.exists():
        return False

    tujuan.write_bytes(contoh.read_bytes())
    return True


def siapkan_folder() -> None:
    for jalur in (
        BACKEND / "data" / "chroma",
        BACKEND / "data" / "uploads",
    ):
        jalur.mkdir(parents=True, exist_ok=True)


def versi(perintah: list[str]) -> str | None:
    """Ambil baris pertama keluaran versi, atau None kalau tidak tersedia.

    `shutil.which` dipakai untuk mendapatkan path sebenarnya, bukan hanya untuk
    memeriksa keberadaan. Di Windows, `npm` adalah `npm.CMD`, dan memanggil
    `npm` tanpa ekstensi gagal walaupun berkasnya ada di PATH. Tanpa ini skrip
    melaporkan npm tidak ditemukan padahal npm terpasang, dan pengguna baru
    mengira pemasangannya belum lengkap.
    """
    jalur = shutil.which(perintah[0])
    if jalur is None:
        return None
    try:
        hasil = subprocess.run(
            [jalur, *perintah[1:]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    baris = ((hasil.stdout or "") + (hasil.stderr or "")).strip().splitlines()
    return baris[0].strip() if baris else None


def main() -> int:
    print("== 1. Perangkat yang dibutuhkan")
    python_v = versi([sys.executable, "--version"])
    node_v = versi(["node", "--version"])
    npm_v = versi(["npm", "--version"])

    print(f"   Python : {python_v or 'TIDAK DITEMUKAN'}")
    print(f"   Node.js: {node_v or 'TIDAK DITEMUKAN'}")
    print(f"   npm    : {npm_v or 'TIDAK DITEMUKAN'}")

    if not node_v:
        print()
        print("   Node.js belum terpasang. Unduh dari https://nodejs.org (pilih LTS).")
        print("   Tanpa Node.js, frontend tidak bisa dijalankan.")

    print()
    print("== 2. Berkas konfigurasi")
    dibuat, sandi = tulis_env_backend()
    if dibuat:
        print("   backend/.env dibuat, dengan passcode acak yang aman.")
    else:
        print("   backend/.env sudah ada, tidak diubah.")

    if tulis_env_frontend():
        print("   frontend/.env.local dibuat dari contoh.")
    else:
        print("   frontend/.env.local sudah ada atau contohnya tidak ditemukan.")

    siapkan_folder()
    print("   Folder data disiapkan: backend/data")

    print()
    print("== 3. Dependency yang sudah terpasang")

    # Python: periksa modul yang dipakai untuk menjalankan backend.
    import importlib.util  # noqa: PLC0415

    modul = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "chromadb": "chromadb",
        "sentence_transformers": "sentence-transformers",
    }
    python_kurang: list[str] = []
    for nama_modul, nama_paket in modul.items():
        ada = importlib.util.find_spec(nama_modul) is not None
        print(f"   python  {nama_paket:<24} {'terpasang' if ada else 'BELUM'}")
        if not ada:
            python_kurang.append(nama_paket)

    # Node: periksa folder node_modules.
    node_modules = FRONTEND / "node_modules"
    node_ada = node_modules.exists() and any(node_modules.iterdir())
    status_node = "ada" if node_ada else "BELUM (jalankan npm install)"
    print(f"   node    node_modules             {status_node}")

    print()
    print("== 4. Langkah berikutnya")

    if python_kurang:
        print("   Pasang dependency Python (sekali saja, 5 sampai 15 menit):")
        print("     cd backend")
        print("     python -m venv .venv")
        print("     .\\.venv\\Scripts\\Activate.ps1")
        print('     pip install -e ".[dev]"')
        print("     pip install sentence-transformers")
        print()

    if not node_ada:
        print("   Pasang dependency frontend (sekali saja):")
        print("     cd frontend && npm install")
        print()

    print("   Menjalankan, di dua terminal:")
    print("     Terminal 1: cd backend && python -m uvicorn app.main:app --port 8000")
    print("     Terminal 2: cd frontend && npm run dev")
    print()
    print("   Buka http://localhost:3000")

    if not python_kurang and node_ada:
        print()
        print("   Semua dependency sudah terpasang. Aplikasi siap dijalankan.")

    if sandi:
        print()
        print("=" * 62)
        print("PASSCODE ANDA (catat sekarang, tidak ditampilkan lagi):")
        print(f"   {sandi}")
        print("=" * 62)
        print("Yang disimpan hanya hash-nya. Kalau hilang, buat yang baru dengan")
        print("  cd backend && python -m scripts.make_passcode")

    return 0


if __name__ == "__main__":
    sys.exit(main())
