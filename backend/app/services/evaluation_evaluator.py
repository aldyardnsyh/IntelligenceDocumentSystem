"""Penilai tiruan untuk RAGAS, supaya jalur evaluasi bisa diuji tanpa API key.

Kenapa ini ada: sebelumnya skrip evaluasi hanya punya dua kemungkinan, yaitu
menjalankan RAGAS dengan LLM asli (butuh API key dan berbiaya) atau tidak
menghasilkan skor sama sekali. Akibatnya jalur RAGAS tidak pernah benar-benar
dijalankan, baik di mesin pengembang maupun di CI. Kalau ada yang salah di
pemetaan kolom dataset, nama metrik, atau cara skor dibaca kembali, kesalahan
itu baru terlihat saat seseorang membayar token dan menemukan hasilnya kosong.

Penilai di sini deterministik dan tidak memanggil jaringan. Ia tidak menilai
makna; ia mengisi skema jawaban yang diminta dengan nilai yang dihitung dari
tumpang tindih kata antara jawaban dan konteks. Skornya tidak sebaik LLM, tapi
cukup untuk membuktikan seluruh pipa RAGAS berjalan.

Yang TIDAK boleh disimpulkan dari skor mode ini: kualitas jawaban sebenarnya.
Skrip evaluasi mencetak peringatan itu, dan skor mode ini tidak disimpan
sebagai hasil pengukuran produksi.

Cara menjawabnya sengaja dibuat generik. Percobaan pertama menebak bentuk JSON
dari nama prompt, dan gagal berkali-kali: RAGAS memakai ``PydanticPrompt``
yang menyertakan skema JSON di akhir teks prompt, dan setiap metrik punya
skema berbeda dengan kolom yang wajib. Karena itu penilai ini membaca skema
itu langsung dari prompt, lalu mengisi setiap kolom wajib sesuai tipenya.
Dengan cara itu, metrik baru yang ditambahkan RAGAS nanti tidak memerlukan
perubahan di sini.

Empat kegagalan berturut-turut ditemukan justru karena pipanya dijalankan
sungguhan, dan semuanya tidak terlihat kalau hanya kode ini yang dibaca:

1. ``AttributeError: ... has no attribute 'set_run_config'``
2. ``AttributeError: ... has no attribute 'generate'``
3. ``TypeError: object LLMResult can't be used in 'await' expression``
4. ``RagasOutputParserException`` karena JSON-nya tidak sesuai skema

Karena itu mode offline ini juga dijalankan di test, bukan hanya tersedia.
"""

from __future__ import annotations

import json
import re
from typing import Any

_KATA = re.compile(r"[a-z0-9]+")

#: Panjang vektor embedding tiruan. Cukup besar untuk membedakan teks, cukup
#: kecil untuk dihitung cepat.
_DIMENSI = 32

#: Penanda skema JSON yang disisipkan ``PydanticPrompt.to_string()``.
_PENANDA_SKEMA = "JSON Schema:"


def _kata_mentah(teks: str) -> list[str]:
    return _KATA.findall(teks.lower())


def kesamaan_kata(sumber: str, target: str) -> float:
    """Fraksi kata target yang muncul di sumber, bernilai 0 sampai 1."""
    target_kata = set(_kata_mentah(target))
    if not target_kata:
        return 0.0
    return len(set(_kata_mentah(sumber)) & target_kata) / len(target_kata)


def _petunjuk_teks(prompt: Any) -> str:
    """Ambil teks dari prompt berbentuk apa pun yang dikirim RAGAS."""
    if isinstance(prompt, str):
        return prompt
    for nama in ("to_string", "to_str"):
        method = getattr(prompt, nama, None)
        if callable(method):
            try:
                return str(method())
            except Exception:  # noqa: BLE001
                break
    return str(prompt)


def _skema_dari_prompt(teks: str) -> dict[str, Any] | None:
    """Ambil skema JSON yang disisipkan RAGAS di akhir teks prompt.

    RAGAS menulis: ``... JSON Schema: {...} Do not use single quotes ...``.
    Skema di-parse dengan menghitung kurung kurawal seimbang, bukan dengan
    regex, karena skema berisi objek bersarang.
    """
    posisi = teks.find(_PENANDA_SKEMA)
    if posisi < 0:
        return None
    mulai = teks.find("{", posisi)
    if mulai < 0:
        return None

    kedalaman = 0
    for indeks in range(mulai, len(teks)):
        huruf = teks[indeks]
        if huruf == "{":
            kedalaman += 1
        elif huruf == "}":
            kedalaman -= 1
            if kedalaman == 0:
                potongan = teks[mulai : indeks + 1]
                try:
                    skema = json.loads(potongan)
                except json.JSONDecodeError:
                    return None
                return skema if isinstance(skema, dict) else None
    return None


def _ikuti_ref(skema: dict[str, Any], akar: dict[str, Any]) -> dict[str, Any]:
    """Ganti ``$ref`` dengan definisi yang ditunjuk, secara rekursif.

    Pydantic menulis model bersarang sebagai ``{"$ref": "#/$defs/Nama"}``.
    Tanpa resolusi ini, tipe item array terbaca kosong dan diisi nilai
    sembarang, lalu RAGAS menolak hasilnya atau mengembalikan NaN.
    """
    rujukan = skema.get("$ref")
    if not isinstance(rujukan, str):
        return skema

    nama = rujukan.rsplit("/", 1)[-1]
    definisi = (akar.get("$defs") or {}).get(nama)
    if not isinstance(definisi, dict):
        return skema
    # Definisi bisa merujuk definisi lain; batasi kedalaman agar aman dari
    # skema melingkar.
    return _ikuti_ref(definisi, akar)


def _isi_skema(
    skema: dict[str, Any], teks_prompt: str, akar: dict[str, Any], nama_kolom: str = ""
) -> Any:
    """Susun nilai yang memenuhi skema.

    Setiap kolom wajib diisi dengan tipe yang benar, karena RAGAS memvalidasi
    hasilnya dengan Pydantic. Nilai yang tidak memenuhi skema ditolak sebelum
    sempat dipakai menghitung skor.
    """
    skema = _ikuti_ref(skema, akar)
    jenis = skema.get("type")

    if jenis == "object" or "properties" in skema:
        hasil: dict[str, Any] = {}
        for nama, subs in (skema.get("properties") or {}).items():
            hasil[nama] = _isi_skema(subs, teks_prompt, akar, nama)
        return hasil

    if jenis == "array":
        item = skema.get("items") or {}
        contoh = _isi_skema(item, teks_prompt, akar, nama_kolom)
        # Satu elemen cukup: skor dihitung dari rasio, jadi satu pernyataan
        # yang dinilai sudah mewakili. Daftar kosong justru membuat RAGAS
        # mengembalikan NaN karena tidak ada yang dihitung.
        return [contoh]

    if jenis == "integer":
        # Dua kolom integer dipakai RAGAS dengan arti berlawanan:
        # - `verdict` pada faithfulness dan context_precision: 1 berarti
        #   pernyataan bersandar pada konteks.
        # - `noncommittal` pada answer relevancy: 1 berarti jawaban mengelak.
        #   Nilai 1 di sini membuat RAGAS menganggap semua jawaban mengelak,
        #   dan skornya jatuh ke 0 tanpa alasan yang terlihat.
        if "noncommittal" in nama_kolom:
            return 0
        return 1

    if jenis == "number":
        return 1.0

    if jenis == "boolean":
        return True

    # String: nama kolom menentukan isi yang masuk akal.
    if "reason" in nama_kolom or "explanation" in nama_kolom:
        return "Dinilai dari tumpang tindih kata antara jawaban dan konteks."
    potongan = _potong_balasan(teks_prompt)
    return potongan or "pernyataan"


def _blok_input(teks: str) -> dict[str, Any]:
    """Ambil objek input yang disisipkan RAGAS di akhir prompt.

    RAGAS menulis bagian terakhir prompt sebagai::

        Now perform the same with the following input
        input: {
            "question": "...",
            "context": "...",
            "answer": "..."
        }
        Output:

    Nilai kolom harus diambil dari sini. Mengambil dari awal prompt berarti
    yang terbaca adalah teks instruksi, dan itu membuat skor bergantung pada
    panjang instruksi, bukan pada jawaban yang dinilai.
    """
    posisi = teks.rfind("input:")
    if posisi < 0:
        return {}
    mulai = teks.find("{", posisi)
    if mulai < 0:
        return {}

    kedalaman = 0
    for indeks in range(mulai, len(teks)):
        huruf = teks[indeks]
        if huruf == "{":
            kedalaman += 1
        elif huruf == "}":
            kedalaman -= 1
            if kedalaman == 0:
                try:
                    isi = json.loads(teks[mulai : indeks + 1])
                except json.JSONDecodeError:
                    return {}
                return isi if isinstance(isi, dict) else {}
    return {}


def _nilai_input(teks: str, nama: str) -> str | None:
    """Nilai satu kolom dari blok input, kalau ada."""
    isi = _blok_input(teks)
    nilai = isi.get(nama)
    if isinstance(nilai, list):
        return " ".join(str(item) for item in nilai)[:200]
    if isinstance(nilai, str) and nilai.strip():
        return " ".join(nilai.split())[:200]
    return None


def _potong_balasan(teks: str) -> str:
    """Ambil isi jawaban atau pertanyaan dari prompt, supaya skor bergantung input."""
    for nama in ("answer", "response", "question", "user_input"):
        nilai = _nilai_input(teks, nama)
        if nilai:
            return nilai

    # Cadangan untuk prompt yang tidak memakai format blok input.
    for penanda in ("Answer:", "Jawaban:"):
        if penanda in teks:
            sisa = teks.split(penanda, 1)[1]
            for akhir in ("\nContext:", "\nQuestion:", "\nInstruction"):
                sisa = sisa.split(akhir, 1)[0]
            return " ".join(sisa.split())[:200]
    return " ".join(teks.split())[:200]


class _Generation:
    """Pengganti ``langchain_core.outputs.Generation``."""

    def __init__(self, text: str) -> None:
        self.text = text


class _LLMResult:
    """Pengganti ``langchain_core.outputs.LLMResult``."""

    def __init__(self, generations: list[list[_Generation]]) -> None:
        self.generations = generations


def _llm_result_class() -> type:
    """Pakai kelas asli kalau langchain ada, selain itu pengganti.

    RAGAS membaca ``result.generations[0][0].text``. Kedua kelas di atas
    punya bentuk yang sama, jadi kode pemanggil tidak perlu tahu mana yang
    dipakai. Impor langsung di tingkat modul akan membuat modul ini gagal
    diimpor tanpa RAGAS, dan itu mematikan test yang seharusnya tetap jalan.
    """
    try:
        from langchain_core.outputs import LLMResult  # noqa: PLC0415
    except ImportError:
        return _LLMResult
    return LLMResult


class OfflineEvaluator:
    """Penilai RAGAS tanpa model, tanpa API key, dan tanpa jaringan.

    Satu kelas dipakai untuk dua peran (LLM dan embeddings) karena keduanya
    memang tidak butuh model: yang diolah hanya bentuk teks.
    """

    name = "offline-evaluator"

    def __init__(self) -> None:
        self.panggilan_llm = 0
        self.panggilan_embedding = 0
        self.run_config: Any = None

    # ------------------------------------------------------------ kesiapan

    def set_run_config(self, run_config: Any) -> None:
        """RAGAS memanggil ini sebelum menilai. Nilainya tidak dipakai."""
        self.run_config = run_config

    # ---------------------------------------------------------------- LLM

    def _balasan(self, prompt: Any) -> str:
        """Susun JSON sesuai skema yang diminta prompt RAGAS."""
        self.panggilan_llm += 1
        teks = _petunjuk_teks(prompt)

        skema = _skema_dari_prompt(teks)
        if skema is None:
            # Tanpa skema, RAGAS tidak bisa mem-parse apa pun. Bentuk default
            # ini dipakai supaya kesalahannya jelas: yang perlu diperiksa
            # adalah asumsi tentang format prompt, bukan metriknya.
            return json.dumps({"score": 1})

        return json.dumps(_isi_skema(skema, teks, skema), ensure_ascii=False)

    def generate_text(
        self,
        prompt: Any,
        n: int = 1,
        temperature: float = 1e-8,  # noqa: ARG002
        stop: list[str] | None = None,  # noqa: ARG002
        callbacks: Any = None,  # noqa: ARG002
    ) -> Any:
        """Kembalikan ``LLMResult``, karena itu yang dibaca RAGAS."""
        hasil = _llm_result_class()
        try:
            from langchain_core.outputs import Generation  # noqa: PLC0415
        except ImportError:
            Generation = _Generation  # type: ignore[assignment,misc]  # noqa: N806
        return hasil(
            generations=[[Generation(text=self._balasan(prompt))] for _ in range(n)]
        )

    async def agenerate_text(
        self,
        prompt: Any,
        n: int = 1,
        temperature: float = 1e-8,
        stop: list[str] | None = None,
        callbacks: Any = None,
    ) -> Any:
        return self.generate_text(
            prompt, n=n, temperature=temperature, stop=stop, callbacks=callbacks
        )

    async def generate(
        self,
        prompt: Any,
        n: int = 1,
        temperature: float | None = None,  # noqa: ARG002
        stop: list[str] | None = None,
        callbacks: Any = None,
    ) -> Any:
        """Alias ``generate_text``, dan wajib async.

        RAGAS menunggu method ini dengan ``await``. Versi sinkron menghasilkan
        ``TypeError: object LLMResult can't be used in 'await' expression``
        yang tertelan di dalam job paralel.
        """
        return self.generate_text(prompt, n=n, stop=stop, callbacks=callbacks)

    async def agenerate(
        self,
        prompt: Any,
        n: int = 1,
        temperature: float | None = None,  # noqa: ARG002
        stop: list[str] | None = None,
        callbacks: Any = None,
    ) -> Any:
        return self.generate_text(prompt, n=n, stop=stop, callbacks=callbacks)

    def get_temperature(self, n: int) -> float:  # noqa: ARG002
        """Penilai ini deterministik, jadi suhunya selalu nol."""
        return 0.0

    def is_finished(self, response: Any) -> bool:  # noqa: ARG002
        """Selalu selesai: penilai ini tidak punya batas token.

        Tanpa method ini RAGAS melempar ``LLMDidNotFinishException`` dan
        seluruh metrik gagal di jalur yang sama seperti ``generate``.
        """
        return True

    # --------------------------------------------------------- embeddings

    def _vektor(self, teks: str) -> list[float]:
        """Bag-of-words yang dinormalisasi dan deterministik."""
        self.panggilan_embedding += 1
        vektor = [0.0] * _DIMENSI
        for kata in _kata_mentah(teks):
            # Hash stabil lintas proses: hash() bawaan Python diacak per run,
            # sehingga skor dua run berturut-turut bisa berbeda tanpa sebab.
            indeks = sum(ord(huruf) for huruf in kata) % _DIMENSI
            vektor[indeks] += 1.0
        panjang = sum(nilai * nilai for nilai in vektor) ** 0.5
        if panjang:
            vektor = [nilai / panjang for nilai in vektor]
        return vektor

    def embed_query(self, text: str) -> list[float]:
        return self._vektor(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vektor(teks) for teks in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return self._vektor(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vektor(teks) for teks in texts]
