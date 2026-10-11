"""Isi database dengan dokumen contoh (FR-8.1).

Portofolio yang dibuka pertama kali dalam keadaan kosong terlihat rusak,
padahal sistemnya sehat. Skrip ini mengunggah satu SOP contoh supaya pengunjung
langsung bisa bertanya dan melihat sitasi bekerja, tanpa harus paham dulu
cara upload dokumen.

Idempoten: aman dijalankan berulang. Kalau dokumen contoh sudah ada (dicek
dari nama berkasnya), skrip tidak melakukan apa-apa dan keluar dengan kode 0.
Menjalankannya dua kali tidak akan menduplikasi apa pun.

Pakai:
    python -m scripts.seed_demo
    docker compose exec api python -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.core.config import get_settings
from app.dependencies import init_services, shutdown_services
from app.repositories.sqlite_repo import SqliteRepository

logger = logging.getLogger(__name__)

SEED_FILENAME = "contoh-sop-layanan.md"

SEED_TEXT = """Standar Operasional Prosedur: Layanan Permintaan Informasi

1. Tujuan
Standar ini mengatur cara Receiving Officer menerima, memverifikasi, dan
menindaklanjuti permintaan informasi yang masuk melalui Satu Pintu Layanan.

2. Ruang Lingkup
Standar ini berlaku untuk seluruh unit kerja. Prosedur ini tidak berlaku untuk
permintaan yang berkaitan dengan data pribadi pihak ketiga yang belum
memperoleh persetujuan tertulis.

3. Definisi
3.1 Receiving Officer adalah pegawai yang ditunjuk sebagai penerima pertama
permintaan informasi.
3.2 SLA Penyelesaian adalah batas waktu maksimal penyelesaian permintaan,
yaitu dua hari kerja sejak permintaan dicatat.

4. Tanggung Jawab
4.1 Receiving Officer wajib mencatat setiap permintaan pada Sistem Tiket dalam
waktu paling lama satu jam kerja.
4.2 Kepala Unit wajib menugaskan petugas teknis yang kompeten sesuai bidang
keahlian, lalu menyatakan kesediaan kepada Receiving Officer.

5. Alur Proses
5.1 Permintaan diterima melalui formulir elektronik atau loket fisik.
5.2 Receiving Officer melakukan verifikasi kelengkapan berkas.
5.3 Bila berkas tidak lengkap, pemohon diberi pemberitahuan tertulis dalam
tempo dua hari kerja.
5.4 Berkas yang lengkap diteruskan ke unit yang diminta.
5.5 Hasil akhir disampaikan kepada pemohon dan dicatat pada Sistem Tiket.

6. Pelaporan
6.1 Laporan bulanan disusun oleh Receiving Officer dan disampaikan kepada
Kepala Unit paling lambat tanggal lima bulan berikutnya.
"""


async def run() -> int:
    settings = get_settings()
    init_services(settings)

    try:
        from app.dependencies import get_ingestion, get_repository

        repository = get_repository()
        ingestion = get_ingestion()

        # Idempotensi dicek dari nama berkas, bukan dari ID: ID dibuat acak
        # setiap upload, jadi tidak bisa dipakai sebagai penanda "sudah ada".
        existing = [
            doc
            for doc in repository.list_documents()
            if doc.filename == SEED_FILENAME and doc.status.value == "ready"
        ]
        if existing:
            print(f"Dokumen contoh sudah ada ({existing[0].id}, ready). Tidak ada yang diubah.")
            return 0

        document = await ingestion.register(
            SEED_FILENAME, SEED_TEXT.encode("utf-8")
        )
        print(f"Dokumen didaftarkan: {document.id} (status: {document.status.value})")

        await ingestion.wait_pending()

        # Baca ulang statusnya. Kalau gagal, laporkan pesannya, jangan
        # diam-diam mengklaim berhasil padahal ingestion-nya error.
        if isinstance(repository, SqliteRepository):
            final = repository.get_document(document.id)
        else:
            final = await asyncio.to_thread(repository.get_document, document.id)

        if final is None or final.status.value != "ready":
            error = final.error_message if final else "dokumen hilang"
            print(f"Ingestion gagal: {error}", file=sys.stderr)
            return 1

        print(f"Siap: {final.chunk_count} chunk terindeks.")
        print()
        print("Coba tanyakan di /chat:")
        print('  "berapa hari untuk penyelesaian permintaan?"')
        return 0
    finally:
        shutdown_services()


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
