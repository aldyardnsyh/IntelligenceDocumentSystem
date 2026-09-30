"""Buat hash SHA-256 dari passcode untuk `ACCESS_PASSCODE_SHA256`.

Kenapa ini skrip dan bukan dokumentasi satu baris `sha256sum`: hash yang salah
ketik hanya akan ketahuan saat semua orang gagal login. Skrip ini mencetak hash
**dan** memverifikasinya sekali jalan, jadi tidak ada yang perlu ditebak.

Pemakaian:
    python -m scripts.make_passcode "passcode-anda"
    python -m scripts.make_passcode --stdin
    python -m scripts.make_passcode
"""

from __future__ import annotations

import getpass
import sys

from app.core.security import hash_passcode, verify_passcode


def _read_passcode() -> str:
    """Ambil passcode dari argumen, stdin, atau prompt interaktif.

    Urutan ini disengaja. Argumen perintah masuk ke riwayat shell **dan**
    terlihat di daftar proses milik user lain, jadi hanya cocok untuk
    otomasi. Untuk pemakaian nyata, `--stdin` atau prompt tanpa echo lebih
    aman karena passcode tidak pernah ditulis ke mana pun.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        return sys.stdin.readline().rstrip("\n")

    if len(sys.argv) > 1:
        return sys.argv[1].strip()

    return getpass.getpass("Passcode: ")


def main() -> int:
    passcode = _read_passcode()

    if not passcode:
        print("Passcode kosong.", file=sys.stderr)
        print(
            "Aplikasi akan menolak semua permintaan login sampai "
            "ACCESS_PASSCODE_SHA256 diisi.",
            file=sys.stderr,
        )
        return 1

    digest = hash_passcode(passcode)

    # Verifikasi sekali jalan. Kalau ada bug di implementasi hashing atau di
    # perbandingannya, di sini baru ketahuan -- bukan setelah semua orang
    # gagal login tanpa tahu kenapa.
    from app.core.config import Settings

    if not verify_passcode(passcode, Settings(access_passcode_sha256=digest)):
        print("Verifikasi gagal: hash tidak cocok dengan passcode aslinya.", file=sys.stderr)
        print("Jangan lanjutkan. Ada bug di implementasi.", file=sys.stderr)
        return 1

    print()
    print("Verifikasi berhasil.")
    print()
    print("Tambahkan baris ini ke backend/.env:")
    print()
    print(f"ACCESS_PASSCODE_SHA256={digest}")
    print()
    print("Lalu muat ulang layanan:")
    print()
    print("    docker compose up -d --force-recreate api")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
