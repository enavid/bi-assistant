interface SpinnerProps {
  size?: number
  className?: string
}

export function Spinner({ size = 22, className = '' }: SpinnerProps) {
  return (
    <svg
      className={`animate-spin ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle cx="12" cy="12" r="10" stroke="var(--border-default)" strokeWidth="2.5" />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        stroke="var(--accent)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function PageLoader() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <Spinner size={28} />
    </div>
  )
}

export function InlineLoader({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-3 px-2">
      <Spinner size={14} />
      {label && <span className="text-[11px]" style={{ color: 'var(--text-3)' }}>{label}</span>}
    </div>
  )
}
