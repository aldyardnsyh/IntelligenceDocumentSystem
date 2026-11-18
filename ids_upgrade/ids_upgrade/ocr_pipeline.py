"""Tahap 1 - render halaman, pra-pemrosesan citra, OCR berurutan-baca, deteksi elemen visual.

Dependensi: pymupdf, opencv-python-headless, pytesseract (+ tesseract-ocr-ind), numpy
Opsional  : anthropic (untuk caption elemen visual / transkripsi halaman via VLM)
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np
import pymupdf
import pytesseract


# ----------------------------------------------------------------------------- data
@dataclass
class Line:
    text: str
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1 (piksel pada DPI render)
    conf: float


@dataclass
class Visual:
    kind: str                         # lambang | tanda_tangan_atau_stempel | paraf | figur
    page: int
    bbox: tuple[int, int, int, int]
    position: str                     # mis. "atas-tengah"
    nearby_text: str = ""
    crop_path: str | None = None
    caption: str | None = None


@dataclass
class PageResult:
    page: int
    width: int
    height: int
    lines: list[Line] = field(default_factory=list)
    visuals: list[Visual] = field(default_factory=list)
    deskew_angle: float = 0.0

    def to_dict(self):
        return asdict(self)


# ----------------------------------------------------------------------------- render
def render_pages(pdf_path: str, dpi: int = 300):
    """Yield (nomor_halaman, citra_grayscale). Dirender ulang dari PDF; tidak mengandalkan
    lapisan teks OCR bawaan scan (urutan baca dan kualitasnya buruk)."""
    doc = pymupdf.open(pdf_path)
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        yield i, np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()


# ----------------------------------------------------------------------------- preprocess
def _estimate_skew(gray: np.ndarray, max_deg: float = 3.0, step: float = 0.25) -> float:
    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    ink = (small < 0.8 * small.mean()).astype(np.uint8) * 255
    h, w = ink.shape
    best, best_score = 0.0, -1.0
    for a in np.arange(-max_deg, max_deg + 1e-6, step):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        rot = cv2.warpAffine(ink, m, (w, h), flags=cv2.INTER_NEAREST)
        score = np.var(rot.sum(axis=1, dtype=np.float64))  # profil proyeksi: garis teks tajam = varians tinggi
        if score > best_score:
            best, best_score = float(a), score
    return best


def preprocess(gray: np.ndarray, denoise: bool = False) -> tuple[np.ndarray, float]:
    """Normalisasi pencahayaan (hilangkan bayangan/noda scan) + deskew."""
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31)
    norm = cv2.divide(gray, bg, scale=255)
    if denoise:
        norm = cv2.fastNlMeansDenoising(norm, None, h=8, templateWindowSize=7, searchWindowSize=15)
    angle = _estimate_skew(norm)
    if abs(angle) >= 0.25:
        h, w = norm.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        norm = cv2.warpAffine(norm, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
    return norm, angle


# ----------------------------------------------------------------------------- OCR
def _merge_rows(lines: list[Line]) -> list[Line]:
    """Gabungkan potongan yang berada pada baris visual yang sama (mis. label 'Menimbang :'
    di kolom kiri dengan isi di kolom kanan), lalu urutkan atas->bawah, kiri->kanan."""
    lines = sorted(lines, key=lambda l: (l.bbox[1] + l.bbox[3]) / 2)
    rows: list[list[Line]] = []
    for ln in lines:
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if rows:
            last = rows[-1]
            ly0 = min(l.bbox[1] for l in last)
            ly1 = max(l.bbox[3] for l in last)
            lh = ly1 - ly0
            if abs(cy - (ly0 + ly1) / 2) < 0.45 * lh:
                last.append(ln)
                continue
        rows.append([ln])
    merged = []
    for r in rows:
        r.sort(key=lambda l: l.bbox[0])
        merged.append(Line(
            text=" ".join(l.text for l in r),
            bbox=(min(l.bbox[0] for l in r), min(l.bbox[1] for l in r),
                  max(l.bbox[2] for l in r), max(l.bbox[3] for l in r)),
            conf=float(np.mean([l.conf for l in r])),
        ))
    return merged


def ocr_lines(img: np.ndarray, lang: str = "ind", psm: int = 4) -> list[Line]:
    cfg = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"
    d = pytesseract.image_to_data(img, lang=lang, config=cfg, output_type=pytesseract.Output.DICT)
    groups: dict[tuple, list] = {}
    for i, txt in enumerate(d["text"]):
        if not txt.strip() or float(d["conf"][i]) < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        groups.setdefault(key, []).append(
            (d["left"][i], d["top"][i], d["width"][i], d["height"][i], txt, float(d["conf"][i])))
    raw = []
    for ws in groups.values():
        ws.sort(key=lambda w: w[0])
        raw.append(Line(
            text=" ".join(w[4] for w in ws),
            bbox=(min(w[0] for w in ws), min(w[1] for w in ws),
                  max(w[0] + w[2] for w in ws), max(w[1] + w[3] for w in ws)),
            conf=float(np.mean([w[5] for w in ws])),
        ))
    return _merge_rows(raw)


# ----------------------------------------------------------------------------- visual elements
def _position_name(bbox, w, h) -> str:
    cx, cy = (bbox[0] + bbox[2]) / 2 / w, (bbox[1] + bbox[3]) / 2 / h
    v = "atas" if cy < 0.33 else "tengah" if cy < 0.66 else "bawah"
    hz = "kiri" if cx < 0.33 else "tengah" if cx < 0.66 else "kanan"
    return f"{v}-{hz}"


def detect_visuals(img: np.ndarray, page: int, lines: list[Line], crop_dir: str | None = None) -> list[Visual]:
    """Heuristik elemen non-teks (lambang, tanda tangan, stempel, paraf):
    blob tinta besar yang tidak berbentuk baris teks. Cukup untuk deteksi + crop; deskripsi
    semantik sebaiknya diberikan VLM (lihat caption_visuals_with_vlm)."""
    h, w = img.shape
    ink = (img < 170).astype(np.uint8) * 255
    # buang piksel yang sudah dikenali sebagai teks (OCR yakin) agar lambang tidak menyatu dengan teks di bawahnya
    for l in lines:
        if l.conf >= 80 and len(l.text) >= 4:
            x0, y0, x1, y1 = l.bbox
            ink[max(y0 - 4, 0):y1 + 4, max(x0 - 4, 0):x1 + 4] = 0
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (35, 35)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    out: list[Visual] = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw < 110 or bh < 110 or bw > 0.45 * w or bh > 0.25 * h:
            continue
        ratio = bw / bh
        if not (0.4 <= ratio <= 3.6):
            continue
        box = (int(x), int(y), int(x + bw), int(y + bh))
        # blob yang isinya didominasi kotak teks OCR = paragraf pendek, bukan visual
        inside = [l for l in lines if l.conf >= 80 and len(l.text) >= 4 and l.bbox[0] >= box[0] - 5 and l.bbox[2] <= box[2] + 5
                  and l.bbox[1] >= box[1] - 5 and l.bbox[3] <= box[3] + 5]
        cover = sum((l.bbox[2] - l.bbox[0]) * (l.bbox[3] - l.bbox[1]) for l in inside) / max(bw * bh, 1)
        if cover > 0.35:
            continue
        pos = _position_name(box, w, h)
        cy = (box[1] + box[3]) / 2 / h
        kind = "lambang" if cy < 0.25 and pos.endswith("tengah") else \
               "paraf" if bw * bh < 0.012 * w * h else "tanda_tangan_atau_stempel"
        # teks terdekat (di bawah/atas blob) membantu pencarian: mis. "PRESIDEN REPUBLIK INDONESIA"
        near = [l.text for l in lines if abs(l.bbox[1] - box[3]) < 0.06 * h and l.bbox[2] > box[0] - 200 and l.bbox[0] < box[2] + 200][:3]
        v = Visual(kind=kind, page=page, bbox=box, position=pos, nearby_text=" | ".join(near))
        if crop_dir:
            os.makedirs(crop_dir, exist_ok=True)
            pad = 12
            crop = img[max(box[1] - pad, 0):box[3] + pad, max(box[0] - pad, 0):box[2] + pad]
            v.crop_path = os.path.join(crop_dir, f"p{page:02d}_{kind}_{i}.png")
            cv2.imwrite(v.crop_path, crop)
        out.append(v)
    return out


# ----------------------------------------------------------------------------- VLM (opsional)
def _b64_png(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf.tobytes()).decode()


def caption_visuals_with_vlm(visuals: list[Visual], model: str | None = None) -> None:
    """Isi Visual.caption lewat Claude vision. Perlu ANTHROPIC_API_KEY. (Belum diuji di sandbox.)"""
    import anthropic
    client = anthropic.Anthropic()
    model = model or os.getenv("VLM_MODEL", "claude-sonnet-5-5")
    for v in visuals:
        if not v.crop_path:
            continue
        img = cv2.imread(v.crop_path)
        r = client.messages.create(
            model=model, max_tokens=200,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64_png(img)}},
                {"type": "text", "text": (
                    "Ini potongan elemen visual dari dokumen hukum Indonesia hasil scan. "
                    "Jelaskan dalam 1-2 kalimat Bahasa Indonesia apa elemen ini (lambang negara, tanda tangan, "
                    "stempel/cap, paraf, atau lainnya) dan teks apa pun yang terbaca di dalamnya. "
                    "Jangan menebak jika tidak jelas.")}]}])
        v.caption = r.content[0].text.strip()


def transcribe_page_with_vlm(img: np.ndarray, model: str | None = None) -> str:
    """Alternatif OCR: transkripsi halaman oleh VLM (lebih akurat pada scan buruk, lebih mahal).
    (Belum diuji di sandbox.)"""
    import anthropic
    client = anthropic.Anthropic()
    model = model or os.getenv("VLM_MODEL", "claude-sonnet-5-5")
    r = client.messages.create(
        model=model, max_tokens=4000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64_png(img)}},
            {"type": "text", "text": (
                "Transkripsikan HANYA teks pada halaman peraturan ini, apa adanya, urut dari atas ke bawah. "
                "Pertahankan nomor Pasal, ayat (1), butir a./1., dan judul BAB/Bagian. "
                "Abaikan nomor halaman dan penanda lanjutan di pojok bawah (mis. 'dalam ...'). "
                "Jangan menambah, mengoreksi isi, atau meringkas.")}]}])
    return r.content[0].text


# ----------------------------------------------------------------------------- orchestrator
def process_pdf(pdf_path: str, dpi: int = 300, crop_dir: str | None = None, denoise: bool = False) -> list[PageResult]:
    results = []
    for no, gray in render_pages(pdf_path, dpi):
        img, angle = preprocess(gray, denoise=denoise)
        lines = ocr_lines(img)
        vis = detect_visuals(img, no, lines, crop_dir)
        results.append(PageResult(page=no, width=img.shape[1], height=img.shape[0],
                                  lines=lines, visuals=vis, deskew_angle=angle))
    return results
