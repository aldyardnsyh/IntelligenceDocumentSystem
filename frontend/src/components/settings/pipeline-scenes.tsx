"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

/**
 * Enam ilustrasi animasi untuk halaman Pengaturan, satu per tahap pipeline.
 *
 * Semua scene berbagi satu bahasa visual dan satu durasi loop (3,6 s) sehingga
 * halaman terasa sebagai satu sistem yang bergerak, bukan enam widget.
 * Bahasa bentuknya konsisten: garis abu muda = konten mentah, garis navy =
 * konten yang sudah diproses, elemen biru brand = bagian yang sedang bekerja.
 *
 * Animasi hanya transform/opacity/clip-path (tidak ada layout property), CSS
 * murni tanpa dependensi, dan dijeda lewat IntersectionObserver saat scene
 * di luar viewport atau tab tersembunyi. Keyframes dan kelas warnanya ada di
 * `globals.css` (awalan `pl-`).
 */

const VIEWBOX = "0 0 240 160";

/** `var(--font-jetbrains)` tidak bisa lewat atribut presentasi SVG. */
const MONO = { fontFamily: "var(--font-jetbrains)" } as CSSProperties;

/**
 * Jeda animasi saat scene tidak terlihat. Loop CSS terus berjalan meski di
 * luar layar; mempause-nya menghemat repaint pada halaman panjang dan tab
 * yang dibuka di latar belakang.
 */
function useAutoPause<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [paused, setPaused] = useState(true);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        setPaused(!entry.isIntersecting || document.hidden);
      },
      { rootMargin: "64px" },
    );
    observer.observe(element);

    // Pindah tab tidak selalu memicu IntersectionObserver, jadi visibility
    // didengarkan terpisah. Kembali ke tab membiarkan observer yang memutus.
    const onVisibility = () => {
      if (document.hidden) setPaused(true);
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return { ref, paused };
}

/** Bingkai scene: SVG dengan viewBox tetap + jeda otomatis. */
function SceneFrame({ children }: { children: ReactNode }) {
  const { ref, paused } = useAutoPause<HTMLDivElement>();

  return (
    <div className="pl-scene" data-paused={paused || undefined} aria-hidden ref={ref}>
      <svg viewBox={VIEWBOX} role="presentation">
        {children}
      </svg>
    </div>
  );
}

/** Penanda posisi kustom untuk keyframes yang muncul di titik berbeda. */
type At = CSSProperties & Record<"--pl-at" | "--pl-to-x" | "--pl-to-y", string | number>;

/* Baris teks stilasi: satu kotak kecil rounded. Ukuran bervariasi agar
   terbaca sebagai paragraf, bukan pola seragam. */
function TextLines({
  x,
  y,
  widths,
  gap = 11,
  className,
}: {
  x: number;
  y: number;
  widths: number[];
  gap?: number;
  className: string;
}) {
  return (
    <>
      {widths.map((width, index) => (
        <rect
          key={`${y + index * gap}-${width}`}
          className={className}
          x={x}
          y={y + index * gap}
          width={width}
          height={4}
          rx={2}
        />
      ))}
    </>
  );
}

/** Tahap 1 — berkas turun masuk ke tumpukan dokumen terupload. */
export function UploadScene() {
  return (
    <SceneFrame>
      {/* tumpukan yang sudah ada */}
      <rect className="pl-ghost" x={42} y={132} width={64} height={7} rx={3} />
      <rect className="pl-ghost" x={46} y={123} width={56} height={7} rx={3} />
      {/* alas tumpukan */}
      <rect className="pl-navy" x={38} y={143} width={72} height={4} rx={2} />

      {/* berkas yang sedang jatuh */}
      <g className="pl-drop">
        <rect
          className="pl-card pl-navy-stroke"
          x={40}
          y={56}
          width={68}
          height={88}
          rx={6}
          strokeWidth={1.5}
        />
        <TextLines className="pl-ghost" x={50} y={72} widths={[44, 48, 36, 44, 28]} />
      </g>

      {/* penanda berhasil masuk */}
      <circle className="pl-arrive pl-brand" cx={110} cy={147} r={4} />
    </SceneFrame>
  );
}

/** Tahap 2 — OCR lokal: garis sapuan memindai, teks terungkap per baris. */
export function OcrScene() {
  const lines = [46, 62, 54, 66, 40, 58, 48, 60];

  return (
    <SceneFrame>
      <rect
        className="pl-card pl-ghost-stroke"
        x={62}
        y={12}
        width={116}
        height={136}
        rx={8}
        strokeWidth={1.5}
      />

      {/* lapisan bawah: teks mentah belum terbaca */}
      <TextLines className="pl-ghost" x={78} y={30} widths={lines} gap={14} />
      {/* lapisan atas: teks hasil OCR, terungkap mengikuti sapuan */}
      <g className="pl-reveal">
        <TextLines className="pl-navy" x={78} y={30} widths={lines} gap={14} />
      </g>

      {/* garis sapuan + bidang pindai tipis */}
      <g className="pl-scan">
        <rect className="pl-brand" x={66} y={10} width={108} height={12} rx={4} opacity={0.12} />
        <rect className="pl-brand" x={66} y={20} width={108} height={2} rx={1} />
      </g>
    </SceneFrame>
  );
}

/** Tahap 3 — chunking struktur: satu halaman terbelah jadi Pasal-Pasal. */
export function ChunkScene() {
  const chunks = [
    { y: 24, h: 40, at: "12%", seam: "8%", seamY: 26 },
    { y: 74, h: 40, at: "38%", seam: "34%", seamY: 76 },
    { y: 124, h: 26, at: "62%", seam: "58%", seamY: 112 },
  ];

  return (
    <SceneFrame>
      {/* halaman sumber */}
      <rect
        className="pl-card pl-ghost-stroke"
        x={10}
        y={22}
        width={62}
        height={118}
        rx={6}
        strokeWidth={1.5}
      />
      <TextLines className="pl-ghost" x={20} y={38} widths={[38, 42, 30, 40, 34, 42, 26]} />

      {/* pemisah struktur (BAB/Pasal) muncul sebelum kotaknya terbentuk */}
      {chunks.map((chunk) => (
        <path
          key={`seam-${chunk.y}`}
          className="pl-seam pl-brand-stroke"
          d={`M 88 ${chunk.seamY} V 138`}
          strokeWidth={1.5}
          strokeDasharray="3 4"
          style={{ "--pl-at": chunk.seam } as At}
        />
      ))}

      {/* chunk hasil: satu Pasal satu kotak */}
      {chunks.map((chunk, index) => (
        <g key={chunk.y} className="pl-chunk-in" style={{ "--pl-at": chunk.at } as At}>
          <rect
            className="pl-card pl-navy-stroke"
            x={98}
            y={chunk.y}
            width={128}
            height={chunk.h}
            rx={5}
            strokeWidth={1.5}
          />
          <text className="pl-brand" x={106} y={chunk.y + 13} fontSize={8} style={MONO}>
            Pasal {index + 1}
          </text>
          <TextLines
            className="pl-navy"
            x={106}
            y={chunk.y + 22}
            widths={chunk.h > 30 ? [96, 104] : [84]}
            gap={9}
          />
        </g>
      ))}
    </SceneFrame>
  );
}

/** Tahap 4 — embedding: chunk terbang jadi titik di ruang vektor. */
export function IndexScene() {
  // Grid 3x3 ruang vektor; tiga di antaranya jadi tujuan chunk.
  const grid = [
    [150, 44], [180, 44], [210, 44],
    [150, 80], [180, 80], [210, 80],
    [150, 116], [180, 116], [210, 116],
  ] as const;
  const targets: Record<number, number> = { 0: 0, 1: 1, 2: 2 };
  const landing = [0, 4, 7];

  return (
    <SceneFrame>
      {/* tiga chunk sumber + titiknya yang terbang ke grid */}
      {[30, 68, 106].map((y, index) => {
        const target = targets[index] !== undefined ? grid[targets[index]] : [180, 80];
        return (
          <g key={y}>
            <rect
              className="pl-card pl-navy-stroke"
              x={10}
              y={y}
              width={60}
              height={26}
              rx={5}
              strokeWidth={1.5}
            />
            <TextLines className="pl-ghost" x={18} y={y + 8} widths={[40, 30]} gap={9} />
            <circle
              className="pl-fly pl-brand"
              cx={76}
              cy={y + 13}
              r={3}
              style={
                {
                  "--pl-at": `${10 + index * 14}%`,
                  "--pl-to-x": `${target[0] - 76}px`,
                  "--pl-to-y": `${target[1] - (y + 13)}px`,
                } as At
              }
            />
          </g>
        );
      })}

      {/* ruang vektor: titik tujuan memantul saat vektor tiba */}
      {grid.map(([x, y], index) => {
        const isTarget = landing.includes(index);
        const order = isTarget ? landing.indexOf(index) : -1;
        return (
          <circle
            key={`${x}-${y}`}
            className={isTarget ? "pl-ping pl-brand" : "pl-ghost"}
            cx={x}
            cy={y}
            r={isTarget ? 4 : 2.5}
            style={isTarget ? ({ "--pl-at": `${44 + order * 14}%` } as At) : undefined}
          />
        );
      })}
      <text className="pl-brand" x={150} y={142} fontSize={8} style={MONO}>
        768 dim
      </text>
    </SceneFrame>
  );
}

/** Tahap 5 — retrieval: pertanyaan menyalakan kandidat, lalu ke model. */
export function RetrievalScene() {
  return (
    <SceneFrame>
      {/* pertanyaan */}
      <rect
        className="pl-wash pl-brand-stroke"
        x={54}
        y={10}
        width={132}
        height={22}
        rx={11}
        strokeWidth={1.5}
      />
      <rect className="pl-navy" x={66} y={19} width={92} height={4} rx={2} />

      {/* denyut 1: pertanyaan turun ke kandidat */}
      <circle
        className="pl-pulse-y pl-brand"
        cx={120}
        cy={34}
        r={3}
        style={{ "--pl-to-y": "44px" } as At}
      />

      {/* kandidat chunk; dua di antaranya menyala saat dilalui */}
      {[
        { x: 44, at: "28%" },
        { x: 92, at: "36%" },
        { x: 140, at: "44%" },
      ].map((candidate) => (
        <rect
          key={candidate.x}
          className="pl-hit pl-card"
          x={candidate.x}
          y={82}
          width={34}
          height={20}
          rx={4}
          stroke="var(--input)"
          strokeWidth={1.5}
          style={{ "--pl-at": candidate.at } as At}
        />
      ))}
      <rect
        className="pl-card"
        x={188}
        y={82}
        width={34}
        height={20}
        rx={4}
        stroke="var(--input)"
        strokeWidth={1.5}
      />

      {/* denyut 2: kandidat terbaik naik ke model bahasa */}
      <circle
        className="pl-pulse-y pl-brand"
        cx={109}
        cy={104}
        r={3}
        style={{ "--pl-at": "48%", "--pl-to-y": "26px" } as At}
      />

      {/* model bahasa */}
      <g className="pl-pop" style={{ "--pl-at": "56%" } as At}>
        <rect
          className="pl-card pl-navy-stroke"
          x={70}
          y={134}
          width={100}
          height={24}
          rx={5}
          strokeWidth={1.5}
        />
        <circle className="pl-brand" cx={82} cy={146} r={3} />
        <rect className="pl-navy" x={92} y={144} width={56} height={4} rx={2} />
      </g>
    </SceneFrame>
  );
}

/** Tahap 6 — jawaban: baris tumbuh streaming, sitasi muncul belakangan. */
export function AnswerScene() {
  return (
    <SceneFrame>
      <rect
        className="pl-card pl-navy-stroke"
        x={28}
        y={22}
        width={148}
        height={104}
        rx={10}
        strokeWidth={1.5}
      />

      {/* jawaban tumbuh per baris, seperti streaming token */}
      <rect className="pl-navy pl-grow" x={42} y={40} width={120} height={5} rx={2.5} style={{ "--pl-at": "6%" } as At} />
      <rect className="pl-navy pl-grow" x={42} y={54} width={104} height={4} rx={2} style={{ "--pl-at": "16%" } as At} />
      <rect className="pl-ghost pl-grow" x={42} y={66} width={116} height={4} rx={2} style={{ "--pl-at": "24%" } as At} />
      <rect className="pl-ghost pl-grow" x={42} y={78} width={88} height={4} rx={2} style={{ "--pl-at": "30%" } as At} />

      {/* sitasi [SUMBER] muncul di kaki jawaban */}
      {[
        { x: 42, label: "SUMBER 1", at: "44%" },
        { x: 112, label: "SUMBER 2", at: "54%" },
      ].map((chip) => (
        <g key={chip.label} className="pl-pop" style={{ "--pl-at": chip.at } as At}>
          <rect
            className="pl-wash pl-brand-stroke"
            x={chip.x}
            y={98}
            width={62}
            height={16}
            rx={8}
            strokeWidth={1.5}
          />
          <text className="pl-brand" x={chip.x + 8} y={109} fontSize={8} style={MONO}>
            {chip.label}
          </text>
        </g>
      ))}

      {/* insight: pulsa satu kali di ujung siklus */}
      <circle
        className="pl-arrive pl-brand"
        cx={176}
        cy={22}
        r={4}
        style={{ "--pl-at": "62%" } as At}
      />
    </SceneFrame>
  );
}
