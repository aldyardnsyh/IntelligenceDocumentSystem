"""Penyimpanan berkas asli yang diunggah.

Kenapa berkas aslinya disimpan: halaman dokumen perlu menampilkan pratinjau
PDF berdampingan dengan daftar chunk. Tanpa berkas aslinya, yang bisa
ditampilkan hanya teks hasil ekstraksi, dan pengguna tidak bisa memeriksa
apakah ekstraksinya benar (tata letak, tabel, atau halaman yang gagal
terbaca).

Penyimpanan ini sengaja terpisah dari vector store dan metadata:

- Berkas ditulis dengan nama dari id dokumen, bukan nama asli dari klien.
  Nama dari klien bisa memuat path, dan path itu tidak boleh menyentuh
  filesystem.
- Ukurannya dibatasi kebijakan unggah yang sudah ada, jadi tidak ada jalur
  baru yang bisa memenuhi disk.
- Kegagalan menulis berkas TIDAK menggagalkan ingestion. Isi dokumen sudah
  tersimpan sebagai chunk, jadi dokumen tetap bisa ditanyai; yang hilang
  hanya pratinjau aslinya.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: Ekstensi yang disimpan sebagai berkas asli. Selain ini hanya teks, dan
#: teks sudah bisa ditampilkan dari chunk tanpa berkas tambahan.
STORED_SUFFIXES = {".pdf"}

_SAFE_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,8}$")


class OriginalFileStore:
    """Simpan dan baca berkas asli per dokumen."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, document_id: str, suffix: str) -> Path:
        # Nama berkas dibangun dari id dokumen (dibuat server) dan ekstensi
        # yang sudah divalidasi. Tidak ada bagian dari nama klien yang ikut,
        # jadi tidak ada cara menyusun path lewat nama berkas.
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "", document_id)
        if not safe_id:
            raise ValueError("id dokumen tidak valid untuk penyimpanan berkas")
        safe_suffix = suffix.lower()
        if not _SAFE_SUFFIX_RE.match(safe_suffix):
            raise ValueError(f"ekstensi tidak aman untuk disimpan: {suffix!r}")
        return self._root / f"{safe_id}{safe_suffix}"

    def should_store(self, filename: str) -> bool:
        """True kalau berkas jenis ini perlu disimpan untuk pratinjau."""
        suffix = Path(filename).suffix.lower()
        return suffix in STORED_SUFFIXES

    def save(self, document_id: str, filename: str, data: bytes) -> str | None:
        """Simpan berkas asli. Kembalikan path relatif, atau None kalau dilewati.

        Tidak melempar: kegagalan menyimpan berkas asli hanya menghilangkan
        pratinjau, sedangkan ingestion-nya tetap harus jalan.
        """
        if not self.should_store(filename):
            return None
        try:
            path = self._path_for(document_id, Path(filename).suffix)
            self._root.mkdir(parents=True, exist_ok=True)
            # Ditulis ke berkas sementara lalu dipindahkan: kalau proses mati
            # di tengah penulisan, yang tersisa bukan berkas separuh yang
            # dianggap valid oleh pembaca PDF.
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(path)
            return path.name
        except Exception:  # noqa: BLE001
            logger.exception(
                "Gagal menyimpan berkas asli %s (%s). Pratinjau PDF untuk dokumen "
                "ini tidak akan tersedia, tapi ingestion tetap berjalan.",
                document_id,
                filename,
            )
            return None

    def load(self, document_id: str, filename: str) -> bytes | None:
        """Baca berkas asli kalau ada."""
        try:
            path = self._path_for(document_id, Path(filename).suffix)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            return path.read_bytes()
        except OSError:
            logger.exception("Gagal membaca berkas asli untuk %s", document_id)
            return None

    def delete(self, document_id: str, filename: str) -> None:
        """Hapus berkas asli. Dipanggil saat dokumen dihapus."""
        try:
            path = self._path_for(document_id, Path(filename).suffix)
        except ValueError:
            return
        for candidate in (path, path.with_suffix(path.suffix + ".part")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                logger.exception("Gagal menghapus berkas asli %s", candidate)
