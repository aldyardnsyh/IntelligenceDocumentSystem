export function TypingDots({ label = "Sedang mencari" }: { label?: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className="flex items-center gap-1" aria-hidden>
        {[0, 1, 2].map((index) => (
          <span
            key={index}
            className="typing-dot size-1.5 rounded-full bg-muted-foreground"
            style={{ animationDelay: `${index * 0.14}s` }}
          />
        ))}
      </span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
