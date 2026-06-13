import { useEffect } from 'react'
import { Icon } from './Icon'

interface ModalProps {
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
}

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  onConfirm: () => void
  onClose: () => void
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Delete', onConfirm, onClose }: ConfirmDialogProps) {
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
      <div className="w-full max-w-xs mx-4 rounded-[14px] shadow-2xl" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)' }}>
        <div className="px-5 pt-5 pb-4">
          <p className="text-[14px] font-semibold mb-1.5" style={{ color: 'var(--text-1)' }}>{title}</p>
          <p className="text-[12px]" style={{ color: 'var(--text-3)' }}>{message}</p>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 pb-5">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-[8px] text-[12px] font-medium transition-colors"
            style={{ background: 'var(--bg-raised)', color: 'var(--text-2)', border: '1px solid var(--border-default)' }}
          >
            Cancel
          </button>
          <button
            onClick={() => { onConfirm(); onClose() }}
            className="px-3.5 py-1.5 rounded-[8px] text-[12px] font-medium transition-colors"
            style={{ background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)' }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
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
      <div className="w-full max-w-sm mx-4 rounded-[14px] shadow-2xl" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)' }}>
        <div className="flex items-center justify-between px-5 py-4 rounded-t-[14px]" style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}>
          <span className="text-[14px] font-semibold" style={{ color: 'var(--text-1)' }}>{title}</span>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-[7px] transition-colors hover:opacity-70" style={{ color: 'var(--text-3)' }}>
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}
