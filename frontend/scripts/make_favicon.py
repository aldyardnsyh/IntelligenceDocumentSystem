"""Buat favicon dari logo aplikasi.

Favicon bawaan create-next-app tidak berhubungan dengan produk ini, jadi tab
browser menampilkan ikon generik. Skrip ini merender ulang bentuk logo
(dokumen terlipat + lencana centang) ke beberapa ukuran ICO.

Warna diambil dari token yang sama dengan logo di UI:
- latar  : --primary  #1e3a5f
- lencana: --brand    #2d9cdb
- kertas : putih, supaya terbaca di latar navy

Jalankan dari direktori `frontend`:

    python scripts/make_favicon.py

Hasilnya menimpa `src/app/favicon.ico`. Next.js membaca berkas itu otomatis
sebagai ikon aplikasi, jadi tidak perlu perubahan kode.
"""

from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

PRIMARY = "#1e3a5f"
BRAND = "#2d9cdb"
SIZES = (16, 32, 48, 64)

#: Bentuk logo pada kanvas 40x40, sama dengan `Logo` di komponen frontend.
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">
  <rect width="40" height="40" rx="10" fill="{primary}"/>
  <path d="M13 9.5h9.2L28 15.3V29a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 12 29V11a1.5 1.5 0 0 1 1-1.5Z"
        fill="none" stroke="#ffffff" stroke-width="2.1" stroke-linejoin="round"/>
  <path d="M22 9.6V15a1 1 0 0 0 1 1h5"
        fill="none" stroke="#ffffff" stroke-width="2.1" stroke-linejoin="round"/>
  <path d="M16 20h8M16 24h5.5"
        stroke="#ffffff" stroke-width="2.1" stroke-linecap="round"/>
  <circle cx="28.5" cy="28.5" r="7.5" fill="{brand}"/>
  <path d="m25 28.6 2.3 2.3 4.4-4.6"
        fill="none" stroke="#ffffff" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def render(size: int) -> Image.Image:
    """Render logo pada ukuran tertentu.

    Digambar pada resolusi 4x lalu diperkecil: tanpa itu, garis tipis logo
    hilang di 16px dan ikonnya terlihat seperti kotak biru kosong.
    """
    scale = 4
    svg = SVG.format(primary=PRIMARY, brand=BRAND)
    document = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
    page = document[0]
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale * size / 40, scale * size / 40),
        alpha=True,
    )
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGBA")
    image = image.resize((size, size), Image.LANCZOS)
    document.close()
    return image


def main() -> int:
    target = Path("src/app/favicon.ico")
    # Pillow menyimpan ICO dari SATU gambar dasar lalu menurunkan ukurannya
    # sendiri. `append_images` tidak dipakai: untuk ICO, Pillow mengabaikannya
    # dan hanya ukuran pertama yang tersimpan.
    base = render(max(SIZES))
    base.save(target, format="ICO", sizes=[(size, size) for size in SIZES])

    written = Image.open(target)
    print(f"favicon ditulis: {target} ({target.stat().st_size} byte)")
    print(f"ukuran tersimpan: {sorted(written.info.get('sizes', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
