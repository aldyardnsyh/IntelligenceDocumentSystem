interface LogoProps {
  size?: number;
  /** Versi ringkas untuk header: dokumen saja, tanpa lencana centang. */
  markOnly?: boolean;
  className?: string;
}

/**
 * Logo ditulis sebagai SVG inline, bukan dari pustaka ikon, karena bentuknya
 * (sudut terlipat + lencana verifikasi yang tumpang tindih) tidak ada di set
 * ikon generik. SVG inline juga ikut ke token warna, jadi tidak perlu berkas
 * terpisah.
 */
export function Logo({ size = 32, markOnly = false, className }: LogoProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-2 ${className ?? ""}`}
      style={{ gap: size * 0.28 }}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 40 40"
        role="img"
        aria-label="Intelligent Document Assistant"
        className="shrink-0"
      >
        <rect width="40" height="40" rx="10" className="fill-primary" />
        <path
          d="M13 9.5h9.2L28 15.3V29a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 12 29V11a1.5 1.5 0 0 1 1-1.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.1"
          strokeLinejoin="round"
          className="text-primary-foreground"
        />
        <path d="M22 9.6V15a1 1 0 0 0 1 1h5" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinejoin="round" className="text-primary-foreground" />
        <path d="M16 20h8M16 24h5.5" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" className="text-primary-foreground" />
        {markOnly ? null : (
          <>
            <circle cx="28.5" cy="28.5" r="7.5" className="fill-brand" />
            <path
              d="m25 28.6 2.3 2.3 4.4-4.6"
              fill="none"
              stroke="#fff"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </>
        )}
      </svg>
    </span>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={`text-[15px] leading-none font-semibold tracking-tight ${className ?? ""}`}>
      Intelligent Document Assistant
    </span>
  );
}
