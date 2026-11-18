"""Deteksi elemen visual halaman hasil pindai.

Lambang, tanda tangan, stempel, dan paraf.

Diporting dari pipeline eksternal (``ids_upgrade/ocr_pipeline.py``) dengan
penyesuaian ke kontrak repo ini: masukan berupa citra halaman + ``OcrLine``
hasil PP-OCR (confidence 0..1, bukan 0..100), dan seluruh deteksi bersifat
OPSIONAL — tanpa OpenCV, fungsi mengembalikan list kosong dan ingestion
berjalan seperti biasa. Pola guard yang sama dengan varian praproses citra.

Heuristiknya: blob tinta besar yang BUKAN baris teks. Piksel yang sudah
dikenali OCR sebagai teks (confidence tinggi) disingkirkan lebih dulu agar
lambang tidak menyatu dengan baris di bawahnya; sisa tinta digabungkan
(morphological close) dan dideteksi sebagai komponen besar. Ketegori
ditentukan dari posisi dan ukuran:
- ``lambang``: di zona kop atas halaman, tengah secara horizontal.
- ``paraf``: blob kecil (tanda tangan basah/paraf di margin teks).
- ``tanda_tangan_atau_stempel``: sisanya, umumnya blok penutup.

Deskripsi semantik (kaption VLM) sengaja belum dipasang: caption template
jenis + posisi + teks terdekat sudah cukup untuk menjawab pertanyaan
"dokumen ini bermaterai siapa / lambang apa di kop", dan VLM menambah biaya
API per halaman yang belum pernah diuji.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Ambang tinta: piksel di bawah kecerahan ini dianggap tinta (kertas pindai
#: tidak putih sempurna; 170 memisahkan tinta dari kertas tanpa tersesat di
#: gradient hasil pemindaian).
_INK_THRESHOLD = 170

#: Ukuran blob yang dianggap elemen visual, bukan noise atau teks.
_MIN_BLOB_SIZE = 110
_MAX_BLOB_WIDTH_RATIO = 0.45
_MAX_BLOB_HEIGHT_RATIO = 0.25

#: Porsi kotak teks di dalam blob: di atas ini berarti blob hanyalah paragraf
#: pendek yang kotak OCR-nya menutupinya, bukan gambar.
_MAX_TEXT_COVER = 0.35


@dataclass(slots=True)
class VisualElement:
    """Satu elemen visual yang terdeteksi di satu halaman."""

    kind: str
    page: int
    bbox: tuple[int, int, int, int]
    position: str
    nearby_text: str
    crop_path: str | None = None
    caption: str | None = None


def _position_name(bbox: tuple[int, int, int, int], w: int, h: int) -> str:
    cx = (bbox[0] + bbox[2]) / 2 / w
    cy = (bbox[1] + bbox[3]) / 2 / h
    vertical = "atas" if cy < 0.33 else "tengah" if cy < 0.66 else "bawah"
    horizontal = "kiri" if cx < 0.33 else "tengah" if cx < 0.66 else "kanan"
    return f"{vertical}-{horizontal}"


def _safe_name(kind: str, index: int) -> str:
    return re.sub(r"[^a-z0-9_]", "_", f"p_{kind}_{index}")


def detect_visuals(
    image,  # noqa: ANN001 - numpy array; cv2 opsional jadi tanpa import keras
    page: int,
    lines,  # noqa: ANN001 - list[OcrLine]
    crop_dir: Path | None = None,
) -> list[VisualElement]:
    """Deteksi elemen visual di satu halaman; butuh OpenCV.

    Returns:
        Elemen terdeteksi, kosong bila OpenCV tidak tersedia atau tidak ada
        blob yang memenuhi kriteria.

    Raises:
        ValueError: Bila dipanggil tanpa OpenCV terpasang — pemanggil wajib
            mengecek ``cv2_available()`` lebih dulu.
    """
    try:
        import cv2  # noqa: PLC0415
        import numpy  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment tanpa cv2
        raise ValueError("Deteksi visual butuh OpenCV (cv2)") from exc

    from app.services.ingestion.ocr_engine import OcrLine  # noqa: PLC0415

    height, width = image.shape[:2]
    gray = image if image.ndim == 2 else None
    if gray is None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = (gray < _INK_THRESHOLD).astype(numpy.uint8) * 255

    def _high_confidence(line: OcrLine) -> bool:
        return line.confidence >= 0.8 and len(line.text) >= 4

    # Singkirkan piksel yang sudah diakui sebagai teks: lambang/stempel di
    # halaman legal sering tumpang-tindih dengan baris kop, dan tanpa ini
    # blob visualnya menyatu dengan teks di bawahnya.
    for line in lines:
        if not _high_confidence(line):
            continue
        x0 = max(int(line.x) - 4, 0)
        y0 = max(int(line.y) - 4, 0)
        x1 = min(int(line.x + line.width) + 4, width)
        y1 = min(int(line.y + line.height) + 4, height)
        ink[y0:y1, x0:x1] = 0

    closed = cv2.morphologyEx(
        ink,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (35, 35)),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(closed, 8)

    out: list[VisualElement] = []
    for index in range(1, count):
        x, y, blob_w, blob_h, _area = stats[index]
        if blob_w < _MIN_BLOB_SIZE or blob_h < _MIN_BLOB_SIZE:
            continue
        if blob_w > _MAX_BLOB_WIDTH_RATIO * width:
            continue
        if blob_h > _MAX_BLOB_HEIGHT_RATIO * height:
            continue
        ratio = blob_w / max(blob_h, 1)
        if not 0.4 <= ratio <= 3.6:
            continue

        box = (int(x), int(y), int(x + blob_w), int(y + blob_h))
        # Blob yang isinya dominan kotak teks = paragraf pendek, bukan gambar.
        inside = [
            line
            for line in lines
            if _high_confidence(line)
            and line.x >= box[0] - 5
            and line.x + line.width <= box[2] + 5
            and line.y >= box[1] - 5
            and line.y + line.height <= box[3] + 5
        ]
        cover = (
            sum((line.width) * (line.height) for line in inside) / max(blob_w * blob_h, 1)
        )
        if cover > _MAX_TEXT_COVER:
            continue

        position = _position_name(box, width, height)
        center_y = (box[1] + box[3]) / 2 / height
        if center_y < 0.25 and position.endswith("tengah"):
            kind = "lambang"
        elif blob_w * blob_h < 0.012 * width * height:
            kind = "paraf"
        else:
            kind = "tanda_tangan_atau_stempel"

        # Teks terdekat di bawah blob (nama pejabat di bawah tanda tangan,
        # "PRESIDEN REPUBLIK INDONESIA" di bawah lambang) yang membuat chunk
        # visual bisa ditemukan lewat kata kunci.
        near = [
            line.text
            for line in lines
            if abs(line.y - box[3]) < 0.06 * height
            and line.x + line.width > box[0] - 200
            and line.x < box[2] + 200
        ][:3]

        element = VisualElement(
            kind=kind,
            page=page,
            bbox=box,
            position=position,
            nearby_text=" | ".join(near),
        )
        if crop_dir is not None:
            crop_dir.mkdir(parents=True, exist_ok=True)
            pad = 12
            y0 = max(box[1] - pad, 0)
            y1 = min(box[3] + pad, height)
            x0 = max(box[0] - pad, 0)
            x1 = min(box[2] + pad, width)
            crop = image[y0:y1, x0:x1]
            crop_path = crop_dir / f"{_safe_name(kind, index)}.png"
            cv2.imwrite(str(crop_path), crop)
            element.crop_path = str(crop_path)
        out.append(element)

    return out


def cv2_available() -> bool:
    """True kalau OpenCV bisa diimpor — deteksi visual opsional terhadap ini."""
    try:
        import cv2  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def build_visual_chunks(
    document_id: str,
    visuals: list[VisualElement],
) -> list[tuple[str, str, int | None]]:
    """Rangkai elemen visual menjadi isi chunk siap-embed.

    Elemen yang berulang tiap halaman (lambang kop, paraf) digabung per jenis
    supaya indeks tidak dibanjiri duplikat; elemen unik (tanda tangan,
    stempel) tetap per kemunculan. Kembalikan pasangan ``(id_chunk, isi,
    halaman)`` — pembuatan Chunk dan embedding-nya tetap di jalur biasa
    supaya satu-satunya tempat pembuatan chunk tidak dipecah.
    """
    repeating = {"lambang", "paraf"}
    groups: dict[str, list[VisualElement]] = {}
    for element in visuals:
        key = element.kind if element.kind in repeating else f"{element.kind}-{element.page}"
        groups.setdefault(key, []).append(element)

    chunks: list[tuple[str, str, int | None]] = []
    for key, elements in groups.items():
        first = elements[0]
        pages = sorted({element.page for element in elements})
        label = first.kind.replace("_", " ")
        text = f"Elemen visual dokumen: {label} di posisi {first.position} halaman."
        if first.nearby_text:
            text += f" Teks di dekatnya: {first.nearby_text}."
        if len(pages) > 1:
            text += f" Elemen serupa muncul berulang pada halaman {pages[0]} sampai {pages[-1]}."
        if first.kind == "lambang":
            text += " Umumnya lambang negara di kop dokumen resmi."
        elif first.kind in ("tanda_tangan_atau_stempel", "paraf"):
            text += " Umumnya tanda tangan, paraf, atau stempel pejabat penandatangan dokumen."
        chunk_id = f"{document_id}_v{len(chunks) + 1}_{re.sub(r'[^a-z0-9]', '', key)}"
        chunks.append((chunk_id, text, pages[0]))
    return chunks
