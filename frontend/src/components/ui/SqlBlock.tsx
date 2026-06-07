import SyntaxHighlighter from 'react-syntax-highlighter'
import { atomOneDark } from 'react-syntax-highlighter/dist/esm/styles/hljs'
import { atomOneLight } from 'react-syntax-highlighter/dist/esm/styles/hljs'
import { useAppStore } from '@/store/appStore'

interface SqlBlockProps {
  code: string
}

export function SqlBlock({ code }: SqlBlockProps) {
  const { theme } = useAppStore()
  const style = theme === 'dark' ? atomOneDark : atomOneLight

  return (
    <SyntaxHighlighter
      language="sql"
      style={style}
      customStyle={{
        margin: 0,
        padding: '12px 16px',
        background: 'transparent',
        fontSize: '12px',
        lineHeight: '1.75',
        fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
      }}
      codeTagProps={{
        style: { fontFamily: 'inherit' },
      }}
    >
      {code}
    </SyntaxHighlighter>
  )
}
