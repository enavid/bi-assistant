import { clsx } from 'clsx'
import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

const variants: Record<Variant, string> = {
  primary:   'bg-accent text-white hover:opacity-90',
  secondary: 'bg-transparent border border-border-default text-text-2 hover:border-border-strong hover:text-text-1',
  ghost:     'bg-transparent text-text-2 hover:bg-bg-raised hover:text-text-1',
  danger:    'bg-transparent border border-red-500/40 text-red-400 hover:bg-red-900/20',
}

const sizes: Record<Size, string> = {
  sm: 'text-[11px] px-2.5 py-1',
  md: 'text-xs px-3.5 py-1.5',
}

export function Button({ variant = 'secondary', size = 'md', className, children, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={clsx(
        'rounded-[7px] font-medium transition-colors disabled:opacity-40 flex items-center gap-1.5 cursor-pointer',
        variants[variant],
        sizes[size],
        className
      )}
    >
      {children}
    </button>
  )
}
