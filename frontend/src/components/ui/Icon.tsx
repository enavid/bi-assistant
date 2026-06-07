type IconName = keyof typeof ICONS

interface IconProps {
  name: IconName
  size?: number
  className?: string
}

export function Icon({ name, size = 16, className }: IconProps) {
  const paths = ICONS[name]
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      {(Array.isArray(paths) ? paths as string[] : [paths as string]).map((d: string, i: number) => (
        <path key={i} d={d} />
      ))}
    </svg>
  )
}

const ICONS = {
  message:        'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  layers:         ['M12 2L2 7l10 5 10-5-10-5z', 'M2 17l10 5 10-5', 'M2 12l10 5 10-5'],
  settings:       ['M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z', 'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'],
  plus:           ['M12 5v14', 'M5 12h14'],
  trash:          ['M3 6h18', 'M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6', 'M10 11v6', 'M14 11v6', 'M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2'],
  copy:           ['M20 9H11a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2z', 'M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'],
  play:           'M5 3l14 9-14 9V3z',
  send:           'M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z',
  check:          'M20 6L9 17l-5-5',
  x:              ['M18 6L6 18', 'M6 6l12 12'],
  sun:            ['M12 1v2', 'M12 21v2', 'M4.22 4.22l1.42 1.42', 'M18.36 18.36l1.42 1.42', 'M1 12h2', 'M21 12h2', 'M4.22 19.78l1.42-1.42', 'M18.36 5.64l1.42-1.42', 'M12 5a7 7 0 1 0 0 14A7 7 0 0 0 12 5z'],
  moon:           'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z',
  'arrow-left':   ['M19 12H5', 'M12 19l-7-7 7-7'],
  'arrow-right':  ['M5 12h14', 'M12 5l7 7-7 7'],
  'bar-chart':    ['M12 20V10', 'M18 20V4', 'M6 20v-4'],
  flask:          ['M9 3h6', 'M10 3v4L5 19a1 1 0 0 0 .9 1.4h12.2A1 1 0 0 0 19 19L14 7V3'],
  notes:          ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M16 13H8', 'M16 17H8', 'M10 9H8'],
  code:           ['M16 18l6-6-6-6', 'M8 6l-6 6 6 6'],
  list:           ['M8 6h13', 'M8 12h13', 'M8 18h13', 'M3 6h.01', 'M3 12h.01', 'M3 18h.01'],
  refresh:        'M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15',
  'bar-h':        ['M3 3v18', 'M7 7h10', 'M7 11h16', 'M7 15h8', 'M7 19h13'],
  donut:          ['M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z', 'M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z'],
  'line-chart':   ['M3 3v18h18', 'M7 14l3-4 4 3 4-8'],
  'area-chart':   ['M3 3v18h18', 'M3 18l4-7 4 4 4-6 4-4v13H3z'],
  server:         ['M2 3h20v6H2z', 'M2 9h20v6H2z', 'M2 15h20v6H2z', 'M6 6h.01', 'M6 12h.01', 'M6 18h.01'],
  database:       ['M12 2a9 3 0 1 0 0 6 9 3 0 0 0 0-6z', 'M21 12c0 1.66-4 3-9 3s-9-1.34-9-3', 'M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5'],
  eye:            ['M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z'],
  grip:           ['M8 6h.01', 'M16 6h.01', 'M8 12h.01', 'M16 12h.01', 'M8 18h.01', 'M16 18h.01'],
} as const
