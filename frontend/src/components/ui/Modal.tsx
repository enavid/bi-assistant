import { useEffect } from 'react'
import { Icon } from './Icon'

interface ModalProps {
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
}

export function Modal({ open, title, onClose, children }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md mx-4 bg-bg-surface border border-border-default rounded-xl overflow-hidden shadow-xl">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-default">
          <span className="text-sm font-medium text-text-1">{title}</span>
          <button onClick={onClose} className="text-text-3 hover:text-text-1 transition-colors p-1">
            <Icon name="x" size={15} />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}
