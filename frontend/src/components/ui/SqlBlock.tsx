import SyntaxHighlighter from 'react-syntax-highlighter'
import { atomOneDark } from 'react-syntax-highlighter/dist/esm/styles/hljs'
import { atomOneLight } from 'react-syntax-highlighter/dist/esm/styles/hljs'
import { format } from 'sql-formatter'
import { useAppStore } from '@/store/appStore'

interface SqlBlockProps {
  code: string
}

function formatSql(sql: string): string {
  try {
    return format(sql, {
      language: 'sql',
      tabWidth: 2,
      keywordCase: 'upper',
      linesBetweenQueries: 1,
    })
  } catch {
    return sql
  }
}

export function SqlBlock({ code }: SqlBlockProps) {
  const { theme } = useAppStore()
  const style = theme === 'dark' ? atomOneDark : atomOneLight  // amin-rai uses light style

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
      {formatSql(code)}
    </SyntaxHighlighter>
  )
}
