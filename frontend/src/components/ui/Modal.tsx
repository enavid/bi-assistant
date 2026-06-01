import { useEffect, useRef } from 'react'
import { clsx } from 'clsx'

interface ModalProps {
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
  width?: string
}

export function Modal({ open, title, onClose, children, width = 'max-w-md' }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === overlayRef.current) onClose() }}
    >
      <div className={clsx('w-full mx-4 bg-bg-surface border border-border-default rounded-xl overflow-hidden', width)}>
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-default">
          <span className="text-sm font-medium text-text-1">{title}</span>
          <button onClick={onClose} className="text-text-3 hover:text-text-1 transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}
