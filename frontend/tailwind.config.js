export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'bg-base':    'var(--bg-base)',
        'bg-surface': 'var(--bg-surface)',
        'bg-raised':  'var(--bg-raised)',
        'bg-hover':   'var(--bg-hover)',
        'border-subtle':  'var(--border-subtle)',
        'border-default': 'var(--border-default)',
        'border-strong':  'var(--border-strong)',
        'text-1': 'var(--text-1)',
        'text-2': 'var(--text-2)',
        'text-3': 'var(--text-3)',
        'accent':        'var(--accent)',
        'accent-bg':     'var(--accent-bg)',
        'accent-border': 'var(--accent-border)',
        'accent-text':   'var(--accent-text)',
        'success':        'var(--green)',
        'success-bg':     'var(--green-bg)',
        'success-border': 'var(--green-border)',
      },
    },
  },
}
