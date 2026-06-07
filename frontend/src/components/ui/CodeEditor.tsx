import { useRef, useEffect, forwardRef, useImperativeHandle } from 'react'

interface CodeEditorProps {
  value: string
  onChange?: (value: string) => void
  onBlur?: (value: string) => void
  readOnly?: boolean
  minHeight?: string
}

export interface CodeEditorHandle {
  getValue: () => string
}

export const CodeEditor = forwardRef<CodeEditorHandle, CodeEditorProps>(
  function CodeEditor({ value, onChange, onBlur, readOnly = false, minHeight = '200px' }, ref) {
    const taRef = useRef<HTMLTextAreaElement>(null)

    useImperativeHandle(ref, () => ({
      getValue: () => taRef.current?.value ?? '',
    }))

    useEffect(() => {
      if (taRef.current && taRef.current.value !== value) {
        taRef.current.value = value
      }
    }, [value])

    function autoResize() {
      const el = taRef.current
      if (!el) return
      el.style.height = 'auto'
      el.style.height = el.scrollHeight + 'px'
    }

    return (
      <div className="relative w-full flex" style={{ minHeight }}>
        <textarea
          ref={taRef}
          defaultValue={value}
          readOnly={readOnly}
          onChange={(e) => { autoResize(); onChange?.(e.target.value) }}
          onBlur={(e) => onBlur?.(e.target.value)}
          onInput={autoResize}
          spellCheck={false}
          className="flex-1 w-full outline-none resize-none border-none text-xs leading-[1.75] font-mono p-3"
          style={{
            minHeight,
            direction: 'ltr',
            textAlign: 'left',
            background: 'var(--bg-raised)',
            color: 'var(--text-1)',
            caretColor: 'var(--accent)',
          }}
        />
      </div>
    )
  }
)
