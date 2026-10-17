"""Test deteksi model embedding berubah, dan pencegahan deadlock di store.

Dua hal yang dikunci di sini.

**Deteksi model berubah.** Vektor dari model berbeda tidak bisa
dibandingkan, dan Chroma tidak tahu itu. Setelah ``EMBEDDING_MODEL``
diganti, koleksi lama tetap ada dan retrieval mengembalikan hasil acak tanpa
satu pun error. Gejalanya menyesatkan: dokumen berstatus ``ready``,
pertanyaan wajar, tapi jawabannya ngawur atau selalu "tidak ditemukan".

**Deadlock lock.** ``query()`` pernah memanggil ``count()`` dari dalam blok
``with self._lock``. ``threading.Lock`` tidak bisa diambil dua kali oleh
thread yang sama, jadi proses menggantung selamanya tanpa pesan apa pun.
Itu membuat satu sesi pengujian macet berjam-jam tanpa petunjuk penyebabnya.
Test di sini memanggil setiap method publik dengan batas waktu, sehingga
deadlock muncul sebagai kegagalan, bukan sebagai hang.

Test memakai Chroma sungguhan di direktori sementara, bukan tiruan, karena
kedua bug itu justru ada di interaksi dengan Chroma.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable

import pytest

from app.core.config import Settings
from app.services.retrieval.vector_store import (
    ChromaVectorStore,
    VectorRecord,
    embedding_signature,
)

COLLECTION = "chunks"
DIMENSI = 8


def _jalankan_dengan_batas_waktu(
    aksi: Callable[[], object], detik: float = 10.0
) -> object:
    """Jalankan aksi di thread terpisah, gagal kalau melewati batas.

    Tanpa ini, deadlock akan menggantung seluruh sesi test dan menyembunyikan
    tes mana yang jadi penyebabnya. Dengan ini, kegagalannya jelas dan
    menunjuk ke method yang salah.
    """
    wadah: dict[str, object] = {}

    def target() -> None:
        try:
            wadah["hasil"] = aksi()
        except Exception as exc:  # noqa: BLE001
            wadah["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(detik)
    if thread.is_alive():
        raise AssertionError(
            f"aksi tidak selesai dalam {detik} detik. Kemungkinan deadlock: "
            "method ini mengambil lock yang sudah dipegang pemanggilnya."
        )
    if "error" in wadah:
        raise wadah["error"]  # type: ignore[misc]
    return wadah.get("hasil")


def _settings(dir_persist: str, model: str, *, lokal: bool = True) -> Settings:
    return Settings(
        chroma_persist_dir=dir_persist,
        embedding_model=model,
        embedding_dimension=DIMENSI,
        use_local_embedding=lokal,
    )


@pytest.fixture
def dir_persist() -> str:
    """Direktori sementara yang tidak dihapus otomatis.

    Chroma menahan handle berkas di Windows, sehingga pembersihan otomatis
    gagal dengan NotADirectoryError. Direktori dibiarkan, sistem yang
    membersihkannya.
    """
    return tempfile.mkdtemp(prefix="uji-signature-")


class TestTandaTanganModel:
    """Tanda tangan harus membedakan konfigurasi yang tidak kompatibel."""

    def test_model_berbeda_tanda_tangan_berbeda(self) -> None:
        a = embedding_signature(_settings("./data", "model-a"))
        b = embedding_signature(_settings("./data", "model-b"))
        assert a != b
        assert "model-a" in a
        assert "model-b" in b

    def test_hashing_berbeda_dari_model_sungguhan(self) -> None:
        asli = embedding_signature(_settings("./data", "model-a", lokal=True))
        stub = embedding_signature(_settings("./data", "model-a", lokal=False))
        assert asli != stub
        assert "hashing-fallback" in stub

    def test_dimensi_stub_ikut_membedakan(self) -> None:
        """Dimensi berbeda berarti ruang vektor berbeda."""
        kecil = Settings(
            embedding_dimension=384, use_local_embedding=False
        )
        besar = Settings(
            embedding_dimension=768, use_local_embedding=False
        )
        assert embedding_signature(kecil) != embedding_signature(besar)

    def test_stabil_untuk_konfigurasi_sama(self) -> None:
        a = embedding_signature(_settings("./data", "model-a"))
        b = embedding_signature(_settings("./data", "model-a"))
        assert a == b


class TestPencatatanDiKoleksi:
    """Tanda tangan harus benar-benar tersimpan, dan tidak merusak koleksi.

    Penandanya sengaja BUKAN metadata koleksi. `Collection.modify` di Chroma
    menolak metadata yang memuat `hnsw:space`, dan kalau kunci itu dibuang,
    Chroma justru menghapus nilainya sehingga koleksi kembali ke jarak L2.
    Itu membuat skor similarity salah tanpa error. Karena itu penandanya
    disimpan sebagai satu baris di dalam koleksi.
    """

    def test_tercatat_setelah_upsert(self, dir_persist: str) -> None:
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))
        store.upsert(
            [VectorRecord(id="c1", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})],
            COLLECTION,
        )
        assert store._baca_tanda_tangan(COLLECTION) == (  # noqa: SLF001
            "sentence-transformers:model-a"
        )

    def test_hnsw_space_tidak_rusak(self, dir_persist: str) -> None:
        """Mencatat tanda tangan tidak boleh mengubah fungsi jarak.

        Ini regresi langsung dari bug yang ditemukan: `modify` menghapus
        `hnsw:space`, sehingga koleksi kembali ke L2 dan skor cosine yang
        dihitung menjadi salah.
        """
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))
        store.upsert(
            [VectorRecord(id="c1", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})],
            COLLECTION,
        )
        handle = store._client.get_collection(COLLECTION)  # noqa: SLF001
        assert dict(handle.metadata or {}).get("hnsw:space") == "cosine"

    def test_count_tidak_menghitung_penanda(self, dir_persist: str) -> None:
        """Baris penanda bukan isi dokumen, jadi tidak dihitung."""
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))
        store.upsert(
            [
                VectorRecord(id=f"c{i}", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})
                for i in range(3)
            ],
            COLLECTION,
        )
        assert store.count(COLLECTION) == 3

    def test_pencarian_tidak_memuat_penanda(self, dir_persist: str) -> None:
        """Penanda tidak boleh muncul sebagai sumber jawaban."""
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))
        store.upsert(
            [VectorRecord(id="c1", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})],
            COLLECTION,
        )
        hasil = store.query([1.0] * DIMENSI, COLLECTION, top_k=5)
        ids = [baris[0] for baris in hasil]
        assert ChromaVectorStore.SIGNATURE_ID not in ids
        assert ids == ["c1"]


class TestDeteksiSaatStart:
    """Ketidakcocokan harus terdeteksi, dan tidak boleh mematikan aplikasi."""

    def test_koleksi_kosong_tidak_melaporkan_masalah(self, dir_persist: str) -> None:
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))
        assert store.signature_mismatch is None

    def test_model_sama_tidak_melaporkan_masalah(self, dir_persist: str) -> None:
        pertama = ChromaVectorStore(_settings(dir_persist, "model-a"))
        pertama.upsert(
            [VectorRecord(id="c1", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})],
            COLLECTION,
        )
        kedua = ChromaVectorStore(_settings(dir_persist, "model-a"))
        assert kedua.signature_mismatch is None

    def test_model_berbeda_terdeteksi_dengan_pesan_perbaikan(
        self, dir_persist: str
    ) -> None:
        pertama = ChromaVectorStore(_settings(dir_persist, "model-a"))
        pertama.upsert(
            [VectorRecord(id="c1", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})],
            COLLECTION,
        )

        kedua = ChromaVectorStore(_settings(dir_persist, "model-b"))
        pesan = kedua.signature_mismatch
        assert pesan is not None, "perubahan model harus terdeteksi"
        assert "model-a" in pesan
        assert "model-b" in pesan
        # Pesannya harus menyebut jalan keluar, bukan hanya "ada yang salah".
        assert "reindex" in pesan

    def test_aplikasi_tetap_jalan_saat_tidak_cocok(self, dir_persist: str) -> None:
        """Deteksi tidak boleh menggagalkan start.

        Operator yang mengganti satu env var tidak boleh membuat seluruh
        layanan mati. Yang benar: layanan jalan, statusnya degraded, dan
        pesannya menyebut perbaikan.
        """
        pertama = ChromaVectorStore(_settings(dir_persist, "model-a"))
        pertama.upsert(
            [VectorRecord(id="c1", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})],
            COLLECTION,
        )
        kedua = ChromaVectorStore(_settings(dir_persist, "model-b"))
        # Store tetap bisa dipakai, hanya ditandai.
        assert kedua.signature_mismatch is not None
        assert kedua.count(COLLECTION) == 1

class TestTidakAdaDeadlock:
    """Setiap method publik harus selesai, bukan menggantung.

    Regresi dari bug nyata: `query()` memanggil `count()` dari dalam blok
    `with self._lock`, dan `threading.Lock` tidak bisa diambil dua kali
    oleh thread yang sama. Akibatnya proses menggantung tanpa pesan, dan satu
    sesi pengujian macet berjam-jam.

    Setiap pemanggilan diberi batas waktu. Kalau deadlock kembali, test gagal
    dengan menyebut method yang salah, bukan menggantung.
    """

    def test_semua_method_publik_selesai(self, dir_persist: str) -> None:
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))

        _jalankan_dengan_batas_waktu(lambda: store.count(COLLECTION))
        _jalankan_dengan_batas_waktu(
            lambda: store.upsert(
                [
                    VectorRecord(
                        id="c1",
                        embedding=[1.0] * DIMENSI,
                        metadata={"content": "isi", "document_id": "d1"},
                    )
                ],
                COLLECTION,
            )
        )

        # Ini yang dulu menggantung: query memanggil count saat lock dipegang.
        hasil = _jalankan_dengan_batas_waktu(
            lambda: store.query([1.0] * DIMENSI, COLLECTION, top_k=5)
        )
        assert isinstance(hasil, list)

        _jalankan_dengan_batas_waktu(lambda: store.count(COLLECTION))
        _jalankan_dengan_batas_waktu(lambda: store.ping())
        _jalankan_dengan_batas_waktu(lambda: store.delete_document("d1", COLLECTION))
        _jalankan_dengan_batas_waktu(lambda: store.delete_collection(COLLECTION))

    def test_query_di_koleksi_kosong_selesai(self, dir_persist: str) -> None:
        """Koleksi kosong juga harus cepat, bukan menggantung."""
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))
        hasil = _jalankan_dengan_batas_waktu(
            lambda: store.query([1.0] * DIMENSI, COLLECTION, top_k=5)
        )
        assert hasil == []

    def test_query_berulang_tidak_menggantung(self, dir_persist: str) -> None:
        """Panggilan berulang tidak boleh saling mengunci."""
        store = ChromaVectorStore(_settings(dir_persist, "model-a"))
        store.upsert(
            [VectorRecord(id="c1", embedding=[1.0] * DIMENSI, metadata={"content": "isi"})],
            COLLECTION,
        )
        for _ in range(5):
            hasil = _jalankan_dengan_batas_waktu(
                lambda: store.query([1.0] * DIMENSI, COLLECTION, top_k=3)
            )
            assert len(hasil) == 1
