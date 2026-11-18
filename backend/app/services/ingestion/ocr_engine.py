"""Mesin OCR lokal: PP-OCR via ONNX Runtime + rekonstruksi urutan baca.

Text-layer rusak pada Lembaran Negara memangkas urutan baca karena layout
dokumen aslinya dua kolom. Mesin PP-OCR mengembalikan **bounding box** untuk
setiap baris, dan dari kotak-kotak itu urutan baca bisa dipulihkan secara
mekanis: kolom dideteksi dari celah vertikal di tengah halaman, isi kolom
kiri dibaca utuh sebelum kolom kanan. Hal yang tidak mungkin dipulihkan dari
text-layer yang sudah kacau, dan yang memakan token API kalau diserahkan ke
model vision.

RapidOCR dipilih sebagai pembawa model PP-OCR karena berjalan di ONNX
Runtime: satu paket pip ringan tanpa runtime PaddlePaddle yang berat, dan
instalasinya sama di Windows developer maupun container Linux.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OcrLine:
    """Satu baris hasil OCR beserta posisinya di halaman.

    Koordinat origin kiri-atas dalam piksel gambar halaman, y bertambah ke
    bawah. ``confidence`` 0..1 dari model pengenalan PP-OCR.
    """

    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


def paddle_available() -> bool:
    """True kalau mesin PP-OCR bisa dimuat di environment ini."""
    try:
        import rapidocr_onnxruntime  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


class PaddleOcrEngine:
    """Pembungkus RapidOCR (model PP-OCR) dengan pemuatan malas.

    Model deteksi+pengenalan dimuat sekali per proses (beberapa detik dan
    belasan MB), bukan per halaman. Thread-safety: RapidOCR tidak dijamin
    thread-safe, dan ingestion berjalan di thread pekerja — kunci memastikan
    dua halaman tidak menembak model yang sama bersamaan.
    """

    name = "paddle"

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    def _get_engine(self):  # noqa: ANN202
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415

                    self._engine = RapidOCR()
                    logger.info("Mesin PP-OCR (RapidOCR) siap.")
        return self._engine

    def recognize_page_voted(
        self,
        image_bytes: bytes,
        *,
        variants: tuple[str, ...] = ("as_is", "clahe_sharpen", "adaptive_threshold"),
        early_exit_confidence: float = 0.75,
        min_chars: int = 40,
        on_variant: Callable[[str, int, float], None] | None = None,
    ) -> tuple[list[OcrLine], dict[str, float]]:
        """Kenali satu halaman lewat beberapa varian citra, lalu vote hasilnya.

        Varian praproses membaca halaman yang sama dari sudut yang berbeda:
        halaman yang tinta capnya menutup baris biasanya bersih pada binarisasi
        adaptif, halaman kontras rendah biasanya bersih pada CLAHE. Satu varian
        yang salah huruf jarang salah di tempat yang sama dengan varian lain —
        kesepakatan mayoritas merekam teks yang benar-benar ada.

        Argumen ini bukan selalu lebih mahal. Halaman yang as-is sudah dibaca
        dengan confidence tinggi dan cukup panjang teksnya berhenti setelah
        varian pertama, jadi halaman bersih tidak membayar biaya varian tambahan.
        Halaman buruk (confidence rendah) membayar hingga len(variants) tahap.

        Args:
            image_bytes: Gambar halaman PNG.
            variants: Nama varian yang dicoba berurutan; ``as_is`` selalu
                di depan supaya early-exit bermakna.
            early_exit_confidence: Ambang confidence halaman as-is untuk berhenti
                membaca varian lebih.
            min_chars: Jumlah karakter minimum halaman as-is supaya early exit
                mengizinkan berhenti; halaman hampir kosong tetap dibaca varian
                lain dan kalau tetap kosong, eskalasi vision yang mengambil.
            on_variant: Callback opsional ``(nama, jumlah baris, confidence)``
                untuk diagnostik.

        Returns:
            Pasangan ``(baris terurut hasil vote, confidence per varian)``.
            Kosong pada map confidence berarti as-is dilepas tanpa vote.

        Raises:
            RuntimeError: Halaman tak bisa dibaca sama sekali.
        """
        if list(variants)[0] != "as_is":
            variants = ("as_is", *variants)

        try:
            prepared = make_preprocess_variants(image_bytes, variants)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Varian praproses gagal dibuat (%s); pakai as-is.", exc)
            lines = self.recognize_page(image_bytes)
            return reconstruct_reading_order(lines), {"as_is": page_confidence(lines)}
        if not prepared:  # pragma: no cover - fallback defensif
            lines = self.recognize_page(image_bytes)
            return reconstruct_reading_order(lines), {"as_is": page_confidence(lines)}

        readings: list[list[OcrLine]] = []
        confidences: dict[str, float] = {}
        for name, payload in prepared:
            lines = self.recognize_page(payload)
            conf = page_confidence(lines)
            confidences[name] = conf
            readings.append(lines)
            if on_variant is not None:
                with contextlib.suppress(Exception):
                    on_variant(name, len(lines), conf)
            chars = sum(len(line.text) for line in lines)
            if name == "as_is" and conf >= early_exit_confidence and chars >= min_chars:
                break

        if len(readings) <= 1:
            return reconstruct_reading_order(readings[0]), confidences

        voted = vote_lines(readings)
        return voted, confidences

    def recognize_page(self, image_bytes: bytes) -> list[OcrLine]:
        """Kenali satu halaman, kembalikan baris dengan kotak dan confidence.

        Args:
            image_bytes: Gambar halaman PNG.

        Returns:
            Daftar OcrLine dalam urutan apa adanya dari mesin (belum
            dipulihkan urutan bacanya); bisa kosong untuk halaman kosong.

        Raises:
            RuntimeError: Mesin gagal mengenali halaman ini.
        """
        import io  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415

        engine = self._get_engine()
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        try:
            raw_result, _elapsed = engine(image)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"PP-OCR gagal mengenali halaman: {exc}") from exc

        lines: list[OcrLine] = []
        if not raw_result:
            return lines
        for box, text, confidence in raw_result:
            if not isinstance(box, (list, tuple)) or len(box) < 4:
                continue
            xs = [float(point[0]) for point in box[:4]]
            ys = [float(point[1]) for point in box[:4]]
            lines.append(
                OcrLine(
                    text=str(text).strip(),
                    confidence=float(confidence),
                    x=min(xs),
                    y=min(ys),
                    width=max(xs) - min(xs),
                    height=max(ys) - min(ys),
                )
            )
        return [line for line in lines if line.text]

    def recover_missing_lines(
        self, image_bytes: bytes, detected: list[OcrLine], *, zoom: float = 2.0
    ) -> list[OcrLine]:
        """Baca ulang celah antar baris dengan zoom tinggi (pass kedua).

        Baris yang tertutup cap tinta sering lolos dari detektor pada citra
        halaman utuh, tapi terbaca kalau band-nya di-crop dan diperbesar.
        Hasilnya baris tambahan dengan koordinat halaman asli, siap digabung
        ke baris utama sebelum rekonstruksi urutan. Band dibatasi 4 per
        halaman supaya halaman buruk tidak menelan waktu ingestion. Fragmen
        yang duduk pada baris visual yang sama digabung menjadi satu baris —
        kotak pecahan seperti "60" yang berdiri sendiri berpola sama dengan
        nomor halaman dan akan terbuang saat teks halaman dibersihkan.
        """
        import io  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415

        image = Image.open(io.BytesIO(image_bytes))
        page_width = float(image.width)
        bands = find_gap_bands(detected, page_width=page_width)[:4]
        if not bands:
            return []

        recovered: list[OcrLine] = []
        for x0, y0, x1, y1 in bands:
            width = max(1, int((x1 - x0) * zoom))
            height = max(1, int((y1 - y0) * zoom))
            crop = image.crop((int(x0), int(y0), int(x1), int(y1))).resize(
                (width, height), Image.LANCZOS
            )
            try:
                found = self.recognize_page(_image_to_png(crop))
            except RuntimeError:
                continue
            for line in found:
                # Koordinat crop diskalakan balik ke koordinat halaman.
                scale_x = (x1 - x0) / width
                scale_y = (y1 - y0) / height
                recovered.append(
                    OcrLine(
                        text=line.text,
                        confidence=line.confidence,
                        x=x0 + line.x * scale_x,
                        y=y0 + line.y * scale_y,
                        width=line.width * scale_x,
                        height=line.height * scale_y,
                    )
                )
        # Baris yang tumpang tindih dengan yang sudah terdeteksi dibuang:
        # tepi band kadang menangkap potongan baris yang sudah ada.
        kept: list[OcrLine] = []
        for line in recovered:
            overlap = any(
                existing.y - 2 <= line.y and line.y <= existing.bottom + 2
                for existing in detected
                if not (line.right < existing.x or line.x > existing.right)
            )
            if not overlap and line.text:
                kept.append(line)
        return _merge_line_fragments(kept)


def make_preprocess_variants(
    image_bytes: bytes,
    variants: tuple[str, ...] = ("as_is", "clahe_sharpen", "adaptive_threshold"),
    *,
    max_side: int = 2600,
) -> list[tuple[str, bytes]]:
    """Hasilkan varian citra halaman untuk dibaca lewat tahap pengenalan.

    Pindai Lembaran Negara punya tiga tantangan sekaligus: tinta cap, muka
    berbayang, dan kontras rendah pada cetakan yang pudar. Satu citra tunggal
    tak bisa menang semua, jadi tiap varian diarahkan ke tantangan berbeda dan
    hasilnya divoting di ``vote_lines``. Varian dipilih karena saling melengkapi,
    bukan karena mirip:

    - ``as_is``: citra mentah. PP-OCR dirancang untuk citra asli; baseline.
    - ``clahe_sharpen``: equalisasi histogram adaptif + penajaman — memperlihatkan
      teks yang pudar.
    - ``adaptive_threshold``: binarisasi lokal — mengubah tulisan buram di bawah
      cap menjadi hitam-putih yang jelas.
    - ``shadow_normalised``: penormalan latar via median blur — meratakan bayang.

    Args:
        image_bytes: Gambar halaman PNG yang akan diolah jadi beberapa varian.
        variants: Nama varian yang diminta; ``as_is`` selalu diperhitungkan.
        max_side: Panjang sisi terbesar yang diterima pemuatan model; citra lebih
            besar akan didownscale agar tidak menambah biaya tanpa manfaat.
    """
    import io  # noqa: PLC0415

    import cv2
    import numpy

    requested = ("as_is", *tuple(v for v in variants if v != "as_is"))
    available = {"as_is", "clahe_sharpen", "adaptive_threshold", "shadow_normalised"}
    requested = tuple(v for v in requested if v in available)
    if not requested:
        requested = ("as_is",)

    decoded = cv2.imdecode(
        numpy.frombuffer(image_bytes, dtype=numpy.uint8), cv2.IMREAD_COLOR
    )
    if decoded is None:  # pragma: no cover - decode gagal pada input rusak
        return [("as_is", image_bytes)]

    big = max(decoded.shape[0], decoded.shape[1])
    scale = 1.0 if big <= max_side else max_side / float(big)
    base = (
        cv2.resize(decoded, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else decoded
    )

    def encode(image: cv2.Mat) -> bytes:
        buffer = io.BytesIO()
        ok, encoded = cv2.imencode(
            ".png", image, [int(cv2.IMWRITE_PNG_COMPRESSION), 1]
        )
        if not ok:  # pragma: no cover - cv2 gagal mengode
            raise RuntimeError("gagal mengode varian citra")
        buffer.write(encoded.tobytes())
        return buffer.getvalue()

    output: list[tuple[str, bytes]] = []
    for name in requested:
        if name == "as_is":
            output.append((name, encode(base)))
        elif name == "clahe_sharpen":
            import numpy  # noqa: PLC0415

            grey = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            kernel = numpy.array(
                [[0.0, -1.0, 0.0], [-1.0, 5.0, -1.0], [0.0, -1.0, 0.0]],
                dtype=numpy.float32,
            )
            sharpened = cv2.filter2D(clahe.apply(grey), -1, kernel)
            output.append((name, encode(sharpened)))
        elif name == "adaptive_threshold":
            grey = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
            blurred = cv2.medianBlur(grey, 3)
            binary = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 8
            )
            output.append((name, encode(binary)))
        elif name == "shadow_normalised":
            grey = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
            background = cv2.medianBlur(grey, 15)
            output.append((name, encode(cv2.divide(grey, background, scale=255))))
    return output


def vote_lines(variants: list[list[OcrLine]], *, agree_ratio: float = 0.6) -> list[OcrLine]:
    """Gabung baris lintas varian dengan voting geometris.

    Baris dari setiap varian terdekat secara geometris dikelompokkan (pusat-y
    dan rentang-x berdekatan), lalu teksnya divoting. Mayoritas teks yang sama
    menang — dan hanya varian yang berjuang dengan keras untuk memulihkan kata
    yang pudar akan berbeda. Teks yang kalah vote dibuang; itu lebih aman
    daripada membiarkan salah satu varian menang hanya karena confidence-nya
    sedikit lebih tinggi.

    Baris yang hanya dipilih satu varian dan berjarak dari grup lain tetap
    dipertahankan — pemilihan varian berbeda bisa membawa baris yang hilang
    pada varian lain (kata yang tertutup cap) dan membuangnya merusak isi.

    Args:
        variants: Baris OCR dari masing-masing varian (maks. 4).
        agree_ratio: Porsi varian yang harus sepakat agar teks dianggap
            disepakati penuh. Di bawah 1.0 supaya varian minoritas yang salah
            baca satu halaman tak bisa memaksakan keputusan.
    """
    if not variants:
        return []
    if len(variants) == 1:
        return reconstruct_reading_order(variants[0])

    ordered = reconstruct_reading_order([line for var in variants for line in var])
    minimum_agree = max(2, int(len(variants) * agree_ratio))

    groups: list[list[OcrLine]] = []
    for line in ordered:
        center = line.y + line.height / 2.0
        tolerance = max(6.0, 0.7 * line.height)
        if groups:
            last = groups[-1][-1]
            last_center = last.y + last.height / 2.0
            near = abs(center - last_center) <= tolerance
            horizontal = not (line.right < last.x or line.x > last.right)
            if near and horizontal:
                groups[-1].append(line)
                continue
        groups.append([line])

    voted: list[OcrLine] = []
    for group in groups:
        # Kelompokkan berdasar teks yang identik di dalam grup geometris; teks
        # yang paling banyak barisnya menang, ties dipecahkan lewat confidence
        # rata-rata.
        counter: dict[str, list[OcrLine]] = {}
        for line in group:
            counter.setdefault(line.text, []).append(line)
        best_text, winner_lines = max(
            counter.items(),
            key=lambda item: (len(item[1]), sum(ln.confidence for ln in item[1]) / len(item[1])),
        )
        # Satu varian yang membaca baris yang tak terbaca varian lain tetap
        # "disepakati" karena tak ada lawan — baris tunggal dianggap bersih.
        agree = len(group) < 2 or len(winner_lines) >= minimum_agree
        best = max(winner_lines, key=lambda line: line.confidence)
        voted.append(
            OcrLine(
                text=best.text,
                # Teks yang ditentangkan dan tidak mencapai kohesi penuh
                # ditandai lebih rendah supaya eskalasi ke vision bisa
                # mempertimbangkan sinyal itu.
                confidence=best.confidence if agree else best.confidence * 0.85,
                x=best.x,
                y=best.y,
                width=best.width,
                height=best.height,
            )
        )
    return voted


def _merge_line_fragments(lines: list[OcrLine]) -> list[OcrLine]:
    """Gabung kotak-kotak fragmen yang duduk pada satu baris visual.

    Membaca ulang band sering memecah satu baris fisik menjadi beberapa kotak
    ("lambat", "60", "(enam", ...). Pecahan itu merusak urutan baca, dan lebih
    parah lagi: kotak angka yang berdiri sendiri seperti "60" berpola sama
    dengan nomor halaman sehingga ikut terbuang saat teks halaman dibersihkan.
    Teks digabung dengan spasi mengikuti urutan x; dua kotak dianggap satu
    baris kalau titik tengah vertikalnya berdekatan relatif terhadap tinggi
    kotaknya.
    """
    if len(lines) <= 1:
        return list(lines)
    ordered = sorted(lines, key=lambda line: (line.y + line.height / 2.0, line.x))
    rows: list[list[OcrLine]] = []
    for line in ordered:
        center = line.y + line.height / 2.0
        if rows:
            last = rows[-1][-1]
            last_center = last.y + last.height / 2.0
            tolerance = 0.5 * max(last.height, line.height)
            if abs(center - last_center) <= tolerance:
                rows[-1].append(line)
                continue
        rows.append([line])

    merged: list[OcrLine] = []
    for row in rows:
        if len(row) == 1:
            merged.append(row[0])
            continue
        row = sorted(row, key=lambda line: line.x)
        x0 = min(line.x for line in row)
        y0 = min(line.y for line in row)
        x1 = max(line.right for line in row)
        y1 = max(line.bottom for line in row)
        merged.append(
            OcrLine(
                text=" ".join(line.text for line in row),
                confidence=sum(line.confidence for line in row) / len(row),
                x=x0,
                y=y0,
                width=x1 - x0,
                height=y1 - y0,
            )
        )
    return merged


def _image_to_png(image: Image.Image) -> bytes:  # noqa: F821
    """Encode PIL Image menjadi PNG bytes untuk pipeline recognisi."""
    import io  # noqa: PLC0415

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _detect_column_gutter(
    lines: list[OcrLine], page_width: float
) -> tuple[float, float] | None:
    """Cari celah vertikal kosong di tengah halaman (penanda dua kolom).

    Cakupan-x semua baris dipetakan ke 100 bucket; celah yang cukup lebar di
    zona tengah halaman berarti layout dua kolom. Header dan footer yang
    membentang selebar halaman menutup celah itu — dan memang benar, karena
    halaman seperti itu sebaiknya dibaca satu kolom saja.
    """
    if page_width <= 0:
        return None
    buckets = 100
    covered = [False] * buckets
    for line in lines:
        start = max(0, min(buckets - 1, int(line.x / page_width * buckets)))
        end = max(0, min(buckets - 1, int(line.right / page_width * buckets)))
        for index in range(start, end + 1):
            covered[index] = True

    # Zona tengah 30%..70%: di luar zona itu, celah di tepi halaman bukan
    # penanda kolom.
    best_start, best_length = None, 0
    run_start = None
    for index in range(30, 71):
        if not covered[index]:
            if run_start is None:
                run_start = index
            run_length = index - run_start + 1
            if run_length > best_length:
                best_start, best_length = run_start, run_length
        else:
            run_start = None

    if best_start is None or best_length < 4:
        return None
    gutter_start = best_start / buckets * page_width
    gutter_end = (best_start + best_length) / buckets * page_width
    return gutter_start, gutter_end


def reconstruct_reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    """Susun baris hasil OCR mengikuti urutan baca manusia.

    Layout satu kolom: atas ke bawah, kiri ke kanan untuk baris sejajar.
    Layout dua kolom: kolom kiri utuh dulu, baru kolom kanan. Baris yang
    membentang melintasi gutter (judul halaman, cap footer) diletakkan di
    awal kalau berada di atas semua isi kolom, kalau tidak di akhir.
    """
    if len(lines) <= 1:
        return list(lines)

    page_width = max(line.right for line in lines)
    gutter = _detect_column_gutter(lines, page_width)
    if gutter is None:
        return sorted(lines, key=lambda line: (line.y, line.x))

    gutter_start, gutter_end = gutter
    tolerance = page_width * 0.02

    left = [line for line in lines if line.right <= gutter_end + tolerance]
    right = [line for line in lines if line.x >= gutter_start - tolerance]
    # Keanggotaan pakai identitas objek, bukan __eq__: dua baris bisa punya isi
    # dan kotak yang identik, dan perbandingan nilai akan salah memindahkan.
    left_ids = {id(line) for line in left}
    right_ids = {id(line) for line in right}
    spanning = [
        line
        for line in lines
        if id(line) not in left_ids and id(line) not in right_ids
    ]

    if not left or not right:
        # Gutter terdeteksi tapi pembagian kosong (semua baris membentang):
        # lebih aman membaca satu kolom.
        return sorted(lines, key=lambda line: (line.y, line.x))

    content_top = min(line.y for line in left + right)
    # Judul halaman berada di atas isi kolom; cap footer di bawahnya.
    spanning_top = [line for line in spanning if line.y < content_top]
    spanning_bottom = [line for line in spanning if line.y >= content_top]

    ordered = [
        *sorted(spanning_top, key=lambda line: (line.y, line.x)),
        *sorted(left, key=lambda line: (line.y, line.x)),
        *sorted(right, key=lambda line: (line.y, line.x)),
        *sorted(spanning_bottom, key=lambda line: (line.y, line.x)),
    ]
    return ordered


def find_gap_bands(
    lines: list[OcrLine], page_width: float
) -> list[tuple[float, float, float, float]]:
    """Cari celah vertikal yang menyimpan baris yang gagal terdeteksi.

    Acuannya **pitch baris** (jarak atas-ke-atas antar baris berurutan dalam
    satu kolom), bukan tinggi baris: satu baris hilang menciptakan jarak
    sekitar 2x pitch, sementara jeda paragraf biasanya 1.5-1.8x pitch. Ambang
    1.6x pitch menangkap kasus baris hilang; jeda paragraf yang ikut tertanda
    tidak berbahaya, band kosongnya hanya dibaca ulang tanpa hasil.

    Setiap band diberi padding vertikal ``max(6.0, 0.8 * median tinggi
    baris)``: band yang terlalu rapat memotong batang huruf dan membuat
    pembacaan ulang gagal — crop yang tepat menempel di antara dua baris
    memangkas ascender/descender baris yang hilang di dalamnya, dan OCR
    mengembalikan teks terpotong. Akibat padding, band bisa sedikit menimpa
    baris tetangga yang sudah terdeteksi; itu tidak masalah karena
    ``recover_missing_lines`` membuang baris hasil pemulihan yang tumpang
    tindih dengan baris yang sudah ada.

    Band dikembalikan per kolom dalam bentuk (x0, y0, x1, y1), terurut dari
    celah terbesar. Murni fungsi geometri: mudah diuji tanpa model.
    """
    if len(lines) < 3 or page_width <= 0:
        return []

    gutter = _detect_column_gutter(lines, page_width)
    groups: list[list[OcrLine]] = []
    if gutter:
        gutter_start, gutter_end = gutter
        tolerance = page_width * 0.02
        left = [line for line in lines if line.right <= gutter_end + tolerance]
        right = [line for line in lines if line.x >= gutter_start - tolerance]
        if left and right:
            groups = [left, right]
    if not groups:
        groups = [lines]

    # Pitch halaman: median jarak atas-ke-atas antar baris sebelahan di semua
    # kolom. Satu nilai untuk seluruh halaman cukup stabil, dan lebih tahan
    # terhadap baris dengan tinggi tidak seragam.
    pitches: list[float] = []
    per_column: list[list[OcrLine]] = []
    for group in groups:
        group = sorted(group, key=lambda line: line.y)
        per_column.append(group)
        pitches.extend(
            current.y - previous.y
            for previous, current in zip(group, group[1:], strict=False)
            if current.y > previous.y
        )
    if not pitches:
        return []
    pitches.sort()
    median_pitch = pitches[len(pitches) // 2]
    min_gap = max(median_pitch * 1.6, 30.0)

    # Padding vertikal band: crop yang tepat menempel di antara dua baris
    # memotong batang huruf baris yang hilang di dalamnya, dan OCR ulang
    # mengembalikan teks terpotong. Pad mengikuti median tinggi baris supaya
    # proporsional dengan ukuran teks di halaman ini.
    heights = sorted(line.height for line in lines if line.height > 0)
    median_height = heights[len(heights) // 2] if heights else 0.0
    pad = max(6.0, median_height * 0.8)

    bands: list[tuple[float, float, float, float]] = []
    for group in per_column:
        col_x0 = min(line.x for line in group)
        col_x1 = max(line.right for line in group)
        for previous, current in zip(group, group[1:], strict=False):
            gap = current.y - previous.y
            if gap < min_gap:
                continue
            # Band meluas ke atas dan ke bawah melewati tepi baris tetangga;
            # hasil yang menimpa baris yang sudah terdeteksi dibuang oleh
            # recover_missing_lines.
            bands.append(
                (col_x0, previous.bottom + 2.0 - pad, col_x1, current.y - 2.0 + pad)
            )

    bands.sort(key=lambda band: band[3] - band[1], reverse=True)
    return bands


def lines_to_page_text(lines: list[OcrLine]) -> str:
    """Gabung baris terurut menjadi teks halaman, dengan paragraf.

    Jeda vertikal yang jauh lebih besar dari tinggi baris biasa berarti
    paragraf baru. Tanpa aturan ini, seluruh halaman menjadi satu blok teks
    dan chunking kehilangan batas paragrafnya.
    """
    if not lines:
        return ""
    heights = sorted(line.height for line in lines if line.height > 0)
    median_height = heights[len(heights) // 2] if heights else 0.0
    paragraph_gap = max(median_height * 2.0, 8.0)

    parts: list[str] = []
    previous: OcrLine | None = None
    for line in lines:
        if previous is not None and line.y - previous.bottom > paragraph_gap:
            parts.append("\n\n")
        elif previous is not None:
            parts.append("\n")
        parts.append(line.text)
        previous = line
    return "".join(parts).strip()


def page_confidence(lines: list[OcrLine]) -> float:
    """Confidence rata-rata halaman, 0.0 untuk halaman tanpa baris."""
    if not lines:
        return 0.0
    return sum(line.confidence for line in lines) / len(lines)
