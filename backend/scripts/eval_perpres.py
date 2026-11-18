"""Evaluasi end-to-end satu dokumen PDF: ingest lalu tanya dataset berlabel.

Skrip ini menguji pipeline persis seperti yang dialami pengguna: PDF
diunggah, di-OCR bila perlu, dipecah per Pasal, diindeks, lalu setiap
pertanyaan dataset dijawab oleh RagService. Berbeda dengan
``scripts/evaluate_ragas.py`` yang butuh LLM penilai tambahan, penilaian di
sini KASAR dan sengaja berlabel jelas: BUKAN PENGGANTI PENILAIAN MANUSIA.

- ``answer``    : persentase kata kunci ``ground_truth`` yang muncul di
  jawaban (token sederhana, lowercase, stopword kecil). Coverage rendah
  belum tentu salah (model boleh memakai sinonim), dan tinggi belum tentu
  benar (jawaban yang salah bisa menyalin kata kunci).
- ``refuse``    : lolos bila pipeline menjawab "tidak ditemukan".
- ``smalltalk`` : lolos bila jawaban terisi dan bukan penolakan.

Angkanya berguna untuk mendeteksi regresi antar run pada korpus yang sama,
bukan untuk menilai kualitas absolut. Dataset bawaan
``evaluation/dataset-perpres.json`` ditulis untuk Perpres 76 Tahun 2013
sebagai CONTOH dataset berlabel, bukan keterikatan korpus: ``--pdf`` selalu
wajib dan berkasnya disediakan pengguna sendiri, tanpa default lokal.

Pakai:
    python -m scripts.eval_perpres --pdf "Perpres 76 2013.pdf" \
        --json-out hasil-eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.models.domain import DocumentStatus
from app.providers.embedding import build_embedding_provider
from app.providers.groq import GroqProvider
from app.repositories.sqlite_repo import SqliteRepository
from app.services.generation.generator import build_chain
from app.services.generation.injection_guard import build_injection_guard
from app.services.ingestion.service import IngestionService
from app.services.memory.store import InMemoryStore
from app.services.rag_service import RagService
from app.services.retrieval.retriever import HybridRetriever
from app.services.retrieval.text_processing import configure_stemming
from app.services.retrieval.vector_store import InMemoryVectorStore

#: Perilaku yang sah pada kolom ``expected_behavior`` dataset.
_BEHAVIORS = ("answer", "refuse", "smalltalk")

#: Kunci wajib satu entri dataset; validasi gagal cepat sebelum eval jalan.
_REQUIRED_KEYS = (
    "id",
    "kategori",
    "question",
    "ground_truth",
    "expected_pasal",
    "expected_behavior",
    "document_name",
)

#: Ambang coverage kata kunci supaya entri ``answer`` dianggap lulus kasar.
#: 60% dipilih agar jawaban benar yang berbeda redaksi masih lolos, sementara
#: jawaban bertopik lain yang hanya menyentuh sebagian kata kunci tidak.
ROUGH_COVERAGE_PASS = 60.0

#: Panjang maksimum cuplikan jawaban yang dicetak di tabel hasil.
_ANSWER_PREVIEW = 160

#: Stopword kecil: kata tugas yang muncul di mana-mana, tidak membawa sinyal.
#: Sengaja TIDAK memuat "tidak", "paling", "tanpa": negasi dan kualifikasi
#: seperti itu membawa makna ("tidak memungut biaya"), membuangnya bisa
#: membuat jawaban yang salah arah tetap dapat skor tinggi.
_STOPWORDS = frozenset(
    {
        "yang", "dan", "atau", "di", "ke", "dari", "dengan", "pada", "dalam",
        "untuk", "adalah", "ini", "itu", "oleh", "sebagai", "kepada", "atas",
        "akan", "juga", "sudah", "saat", "bila", "jika", "maka", "serta",
        "yaitu", "yakni", "antara", "seperti", "bisa", "dapat", "bagi",
    }
)

#: Dataset relatif dihitung dari direktori backend, bukan dari cwd, supaya
#: skrip tetap benar saat dijalankan dari akar repo.
_BACKEND_DIR = Path(__file__).resolve().parent.parent

#: Angka dengan glos ejaan, mis. "3 (tiga)" atau "21 (dua puluh satu)",
#: adalah SATU fakta yang sama. Tanpa normalisasi ini, jawaban yang menulis
#: "3 BAB" dianggap kehilangan kata kunci "tiga" padahal tidak ada informasi
#: yang hilang; coverage menjadi false negative. Hanya glos yang menempel
#: langsung pada angka yang dibuang, jadi "Pasal 12 ayat (3)" tidak tersentuh.
_ANGKA_BERGLOS = re.compile(r"(\d+)\s*\([^)]*\)")


def kata_kunci(teks: str) -> list[str]:
    """Pecah teks jadi kata kunci: lowercase, alfanumerik, tanpa stopword.

    Angka selalu dipertahankan berapa pun panjangnya: "60 hari", "Pasal 12",
    dan "Nomor 191" adalah kunci jawaban yang paling tidak boleh hilang.
    Sebaliknya huruf tunggal ("huruf b") bawa noise, bukan sinyal.
    """
    teks = _ANGKA_BERGLOS.sub(r"\1", teks)
    tokens = re.findall(r"[a-z0-9]+", teks.lower())
    return [
        token
        for token in tokens
        if (token.isdigit() or len(token) >= 3) and token not in _STOPWORDS
    ]


def coverage_kata_kunci(ground_truth: str, jawaban: str) -> tuple[float, list[str]]:
    """Persentase kata kunci ground_truth yang muncul di jawaban.

    Mengembalikan (persen, daftar kata kunci yang hilang). Daftar yang
    hilang ikut ditulis ke hasil ``--json-out`` supaya entri yang gagal bisa
    dinilai ulang dengan mata, tanpa menebak kata mana yang tidak muncul.
    """
    kunci = list(dict.fromkeys(kata_kunci(ground_truth)))
    if not kunci:
        return 100.0, []
    token_jawaban = set(kata_kunci(jawaban))
    hilang = [kata for kata in kunci if kata not in token_jawaban]
    persen = round(100.0 * (len(kunci) - len(hilang)) / len(kunci), 1)
    return persen, hilang


def load_dataset(path: Path, limit: int | None) -> list[dict[str, Any]]:
    """Baca dan validasi dataset berlabel.

    Validasi gagal cepat dengan pesan yang menunjuk entri bermasalah, bukan
    berjalan setengah jalan lalu KeyError di tengah evaluasi.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Dataset harus berupa JSON array.")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Entri {index} harus berupa objek.")
        hilang = [kunci for kunci in _REQUIRED_KEYS if kunci not in item]
        if hilang:
            raise ValueError(f"Entri {index} kehilangan kunci: {', '.join(hilang)}.")
        if item["expected_behavior"] not in _BEHAVIORS:
            raise ValueError(
                f"Entri {index} ('{item['id']}') punya expected_behavior "
                f"'{item['expected_behavior']}' di luar {_BEHAVIORS}."
            )
        pasal = item["expected_pasal"]
        if not isinstance(pasal, list) or not all(isinstance(n, int) for n in pasal):
            raise ValueError(
                f"Entri {index} ('{item['id']}'): expected_pasal harus list int."
            )
    if limit is not None and limit > 0:
        data = data[:limit]
    return data


def resolve_path(raw: str, base: Path) -> Path:
    """Path absolut dilewati apa adanya; path relatif dihitung dari ``base``."""
    path = Path(raw).expanduser()
    return path if path.is_absolute() else base / path


def ringkasan_konfigurasi(settings: Settings) -> dict[str, Any]:
    """Potongan konfigurasi yang menentukan perilaku eval, untuk cetak dan JSON."""
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "fallback_chain": list(settings.llm_fallback_chain),
        "embedding_lokal": settings.use_local_embedding,
        "embedding_model": settings.embedding_model,
        "pdf_mode": settings.ingest_pdf_mode,
        "ocr_engine": settings.ocr_engine,
        "prompt_guard": settings.prompt_guard_enabled,
        "prompt_guard_threshold": settings.prompt_guard_threshold,
        "similarity_threshold": settings.default_similarity_threshold,
        "weak_evidence_floor": settings.weak_evidence_floor,
    }


def cetak_konfigurasi(konfigurasi: dict[str, Any]) -> None:
    """Cetak ringkasan konfigurasi sebelum pekerjaan berat dimulai.

    Provider dan ambang sangat menentukan hasil eval; tanpa ringkasan ini,
    angka dari run yang dikonfigurasi berbeda terbanding apa adanya dan
    kesimpulannya menyesatkan.
    """
    guard_teks = (
        f"aktif (threshold {konfigurasi['prompt_guard_threshold']})"
        if konfigurasi["prompt_guard"]
        else "mati (bertahan pada aturan prompt)"
    )
    embedding_teks = (
        str(konfigurasi["embedding_model"])
        if konfigurasi["embedding_lokal"]
        else "hashing fallback (tanpa model lokal)"
    )
    provider_teks = (
        f"{konfigurasi['llm_provider']} (model {konfigurasi['llm_model']})"
    )
    print("== Konfigurasi ==")
    print(f"  provider generation : {provider_teks}")
    rantai = ", ".join(str(item) for item in konfigurasi["fallback_chain"]) or "-"
    print(f"  fallback chain      : {rantai}")
    print(f"  embedding           : {embedding_teks}")
    print(
        f"  pdf / ocr engine    : {konfigurasi['pdf_mode']} / "
        f"{konfigurasi['ocr_engine']}"
    )
    print(f"  guard injection     : {guard_teks}")
    print(
        "  ambang retrieval    : similarity "
        f"{konfigurasi['similarity_threshold']}, "
        f"weak evidence {konfigurasi['weak_evidence_floor']}"
    )
    if konfigurasi["llm_provider"] == "mock":
        print(
            "  PERINGATAN: LLM_PROVIDER=mock. Jawaban berasal dari stub, jadi "
            "angka penilaian tidak menggambarkan kualitas provider nyata."
        )


async def uji_entri(
    rag: RagService, entri: dict[str, Any], document_id: str
) -> dict[str, Any]:
    """Jawab satu pertanyaan dataset dan nilai kasar sesuai expected_behavior.

    Event dikumpulkan sampai selesai, tidak berhenti di not_found: pada
    jalur cache, event not_found dikirim SETELAH token jawaban, jadi
    berhenti lebih awal bisa kehilangan cuplikan jawaban atau sitasi.
    """
    potongan: list[str] = []
    halaman: list[int] = []
    not_found = False
    weak_evidence = False
    ungrounded = False
    error: str | None = None
    try:
        async for event in rag.answer(entri["question"], None, [document_id]):
            if event.type == "token":
                potongan.append(str(event.value))
            elif event.type == "citations":
                for citation in event.value:  # type: ignore[union-attr]
                    page = getattr(citation, "page_number", None)
                    if isinstance(page, int) and page not in halaman:
                        halaman.append(page)
            elif event.type == "not_found":
                not_found = True
            elif event.type == "weak_evidence":
                weak_evidence = True
            elif event.type == "ungrounded":
                ungrounded = True
            elif event.type == "error":
                error = str(event.value)
    except Exception as exc:
        # Satu entri gagal tidak boleh menjatuhkan seluruh evaluasi; hasil
        # parsial per entri tetap lebih informatif daripada tidak sama sekali.
        error = f"{type(exc).__name__}: {exc}"

    jawaban = "".join(potongan).strip()
    behavior = str(entri["expected_behavior"])
    coverage: float | None = None
    hilang: list[str] = []
    lulus = False
    alasan = ""
    if error is not None:
        alasan = f"error pipeline: {error}"
    elif behavior == "answer":
        coverage, hilang = coverage_kata_kunci(str(entri["ground_truth"]), jawaban)
        lulus = coverage >= ROUGH_COVERAGE_PASS and not not_found
        if not lulus:
            alasan = (
                "jawaban ditolak (not_found), seharusnya menjawab"
                if not_found
                else f"coverage {coverage}% di bawah ambang {ROUGH_COVERAGE_PASS}%"
            )
    elif behavior == "refuse":
        # Dua bentuk penolakan yang sah: (1) pipeline menolak (not_found),
        # (2) model menjawab tapi isinya menyatakan informasi tidak ada di
        # dokumen (menolak secara natural tanpa memicu not_found, karena
        # retrieval menemukan chunk bertopik). Keduanya sama-sama baik untuk
        # pertanyaan di luar dokumen; yang TIDAK sah adalah menjawab dengan
        # informasi yang dikarang.
        jawaban_rendah = jawaban.lower()
        tolak_via_teks = (
            "tidak ditemukan" in jawaban_rendah
            or "tidak membahas" in jawaban_rendah
            or "tidak memuat" in jawaban_rendah
            or "tidak termuat" in jawaban_rendah
            or "tidak mencantumkan" in jawaban_rendah
            or "tidak tercantum" in jawaban_rendah
            or "tidak disebutkan" in jawaban_rendah
            or "tidak menetapkan" in jawaban_rendah
            or "tidak merinci" in jawaban_rendah
            or "tidak tersedia" in jawaban_rendah
            or "tidak diatur" in jawaban_rendah
            or "tidak mengatur" in jawaban_rendah
            or "tidak terdapat" in jawaban_rendah
            or "tidak ada dalam dokumen" in jawaban_rendah
            or "tidak ada pada dokumen" in jawaban_rendah
            or "tidak dijumpai" in jawaban_rendah
        )
        lulus = not_found or tolak_via_teks
        alasan = "" if lulus else "sistem menjawab dengan mengarang alih-alih menolak"
    elif behavior == "smalltalk":
        lulus = bool(jawaban) and not not_found
        alasan = "" if lulus else "jawaban kosong atau jatuh ke penolakan"

    return {
        "id": entri["id"],
        "kategori": entri["kategori"],
        "question": entri["question"],
        "expected_behavior": behavior,
        "expected_pasal": entri["expected_pasal"],
        "answer": jawaban,
        "not_found": not_found,
        "weak_evidence": weak_evidence,
        "ungrounded": ungrounded,
        "error": error,
        "halaman_sitasi": sorted(halaman),
        "coverage": coverage,
        "kata_kunci_hilang": hilang,
        "lulus": lulus,
        "alasan": alasan,
    }


def cetak_hasil(rows: list[dict[str, Any]]) -> None:
    """Cetak baris per entri: id, kategori, behavior, kasar, sitasi, jawaban."""
    total = len(rows)
    print()
    print("== Hasil per entri (penilaian KASAR, bukan pengganti penilaian manusia) ==")
    for nomor, row in enumerate(rows, start=1):
        status = "OK" if row["lulus"] else "GAGAL"
        coverage_kolom = (
            f" | coverage {row['coverage']}%" if row["coverage"] is not None else ""
        )
        print(
            f"[{nomor}/{total}] {row['id']} ({row['kategori']}) | "
            f"{row['expected_behavior']} | {status}{coverage_kolom}"
        )
        pelengkap = []
        if row["not_found"]:
            pelengkap.append("not_found")
        if row["weak_evidence"]:
            pelengkap.append("weak_evidence")
        if row["ungrounded"]:
            pelengkap.append("ungrounded")
        if row["error"]:
            pelengkap.append(f"error: {row['error']}")
        sitasi = ", ".join(str(page) for page in row["halaman_sitasi"]) or "-"
        baris_sitasi = f"    sitasi hlm : {sitasi}"
        if pelengkap:
            baris_sitasi += f" | {'; '.join(pelengkap)}"
        print(baris_sitasi)
        if row["alasan"]:
            print(f"    catatan    : {row['alasan']}")
        utuh = " ".join(str(row["answer"]).split())
        cuplikan = utuh[:_ANSWER_PREVIEW]
        if len(utuh) > _ANSWER_PREVIEW:
            cuplikan += "..."
        print(f"    jawaban    : {cuplikan or '(kosong)'}")


def cetak_ringkasan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cetak ringkasan lulus/gagal total dan per perilaku, lalu kembalikannya."""
    total = len(rows)
    lulus = sum(1 for row in rows if row["lulus"])
    per_behavior: dict[str, dict[str, int]] = {}
    for row in rows:
        statistik = per_behavior.setdefault(
            str(row["expected_behavior"]), {"total": 0, "lulus": 0}
        )
        statistik["total"] += 1
        statistik["lulus"] += 1 if row["lulus"] else 0

    print()
    print("== Ringkasan ==")
    print(f"  lulus (kasar) : {lulus}/{total}")
    for behavior in _BEHAVIORS:
        statistik = per_behavior.get(behavior)
        if statistik is not None:
            print(f"  {behavior:<9} : {statistik['lulus']}/{statistik['total']}")
    return {
        "total": total,
        "lulus": lulus,
        "gagal": total - lulus,
        "per_behavior": per_behavior,
    }


async def jalankan(args: argparse.Namespace) -> int:
    """Seluruh alur: dataset -> ingestion PDF -> tanya-jawab -> penilaian kasar."""
    dataset_path = resolve_path(str(args.dataset), _BACKEND_DIR)
    if not dataset_path.exists():
        print(f"Dataset tidak ditemukan: {dataset_path}", file=sys.stderr)
        return 2
    pdf_path = resolve_path(str(args.pdf), Path.cwd())
    if not pdf_path.exists():
        print(f"File PDF tidak ditemukan: {pdf_path}", file=sys.stderr)
        return 2

    try:
        dataset = load_dataset(dataset_path, args.limit)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Dataset tidak valid: {exc}", file=sys.stderr)
        return 2

    settings = Settings()
    konfigurasi = ringkasan_konfigurasi(settings)
    cetak_konfigurasi(konfigurasi)

    print()
    print("== Ingestion ==")
    repository = SqliteRepository(str(args.db), defaults=settings)
    # Stemming BM25 disetel SEBELUM dokumen diindeks: token dokumen dan query
    # harus memakai pemroses yang sama, dan konfigurasinya dibaca sekali.
    configure_stemming(settings)
    # SATU vector store dipakai bersama oleh ingestion dan retriever, sama
    # seperti dependency injection produksi. Dua store terpisah membuat
    # jawaban "tidak ditemukan" pada corpus yang jelas sudah terindeks.
    store = InMemoryVectorStore()
    retriever = HybridRetriever(store)
    embedding = build_embedding_provider(settings)
    memory = InMemoryStore()
    ingestion = IngestionService(settings, repository, store, retriever, embedding, memory)

    document = await ingestion.register(pdf_path.name, pdf_path.read_bytes())
    await ingestion.wait_pending()

    stored = repository.get_document(document.id)
    if stored is None:
        print("Dokumen tidak ada di repository setelah ingestion selesai.", file=sys.stderr)
        return 2
    print(f"  id      : {stored.id}")
    print(f"  nama    : {stored.filename}")
    print(f"  status  : {stored.status.value}")
    print(f"  halaman : {stored.page_count}")
    print(f"  chunk   : {stored.chunk_count}")
    if stored.status is not DocumentStatus.READY:
        print(
            f"Ingestion tidak READY (status {stored.status.value}): "
            f"{stored.error_message}",
            file=sys.stderr,
        )
        return 2

    # Pola bangun manual mengikuti dependencies.py dan fixture test: guard
    # dipin ke Groq hanya kalau API key ada; tanpa itu screening tidak jalan
    # dan keamanan bertahan pada aturan prompt.
    chain = build_chain(settings)
    guard = build_injection_guard(
        settings, GroqProvider(settings) if settings.groq_api_key else None
    )
    rag = RagService(settings, repository, memory, retriever, embedding, chain, None, guard)

    print()
    print(f"== Menjawab {len(dataset)} pertanyaan ==")
    rows: list[dict[str, Any]] = []
    for entri in dataset:
        rows.append(await uji_entri(rag, entri, stored.id))

    cetak_hasil(rows)
    ringkasan = cetak_ringkasan(rows)

    if args.json_out:
        jalur_out = resolve_path(str(args.json_out), Path.cwd())
        payload = {
            "catatan": (
                "Penilaian kasar berbasis kata kunci; bukan pengganti penilaian manusia."
            ),
            "dataset": str(dataset_path),
            "pdf": str(pdf_path),
            "dokumen": {
                "id": stored.id,
                "nama": stored.filename,
                "status": stored.status.value,
                "halaman": stored.page_count,
                "chunk": stored.chunk_count,
            },
            "konfigurasi": konfigurasi,
            "ringkasan": ringkasan,
            "hasil": rows,
        }
        jalur_out.parent.mkdir(parents=True, exist_ok=True)
        jalur_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print()
        print(f"Hasil lengkap ditulis ke {jalur_out}")

    # Kode keluar ramah CI: 2 untuk kegagalan lingkungan (dataset, PDF,
    # ingestion), 1 kalau ada entri yang gagal penilaian kasar, 0 kalau bersih.
    return 0 if ringkasan["gagal"] == 0 else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Argumen CLI; --pdf wajib dan tanpa default ke berkas lokal mana pun."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.eval_perpres",
        description=(
            "Evaluasi end-to-end satu dokumen PDF: ingest, lalu jawab dataset "
            "berlabel dengan penilaian kasar berbasis kata kunci. Penilaian "
            "ini bukan pengganti penilaian manusia."
        ),
        epilog=(
            "Contoh:\n"
            '  python -m scripts.eval_perpres --pdf "Perpres 76 2013.pdf" '
            "--json-out hasil-eval.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        default="evaluation/dataset-perpres.json",
        help="Path dataset JSON (relatif dihitung dari direktori backend).",
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path dokumen PDF yang diuji (dokumen Anda sendiri).",
    )
    parser.add_argument(
        "--db",
        default="./data/eval-e2e.db",
        help="Path database SQLite untuk eval (relatif dihitung dari cwd).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Batasi jumlah entri yang diuji, mis. --limit 5.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Path berkas JSON untuk hasil lengkap (relatif dihitung dari cwd).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Titik masuk CLI."""
    return asyncio.run(jalankan(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
