/* 앱 전용 선 아이콘. 외부 아이콘 글꼴 대신 SVG로 그려서 운영체제나
   글꼴에 따라 모양이 달라지지 않는다. 모두 같은 선 굵기와 둥근 끝을 쓴다. */
const paths = {
  home: <><path d="m3 10 9-7 9 7" /><path d="M5 9v11h14V9" /><path d="M9 20v-6h6v6" /></>,
  results: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4M17 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01" /></>,
  user: <><circle cx="12" cy="8" r="3" /><path d="M5 21a7 7 0 0 1 14 0" /></>,
  pill: <><path d="m8.5 5.5 10 10a4.24 4.24 0 0 1-6 6l-10-10a4.24 4.24 0 0 1 6-6Z" /><path d="m5.5 8.5 10 10" /></>,
  hospital: <><path d="M4 21V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v16" /><path d="M9 21v-4h6v4M8 8h8M12 5v6" /></>,
  search: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.2-4.2" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.6 2.6 0 1 1 4.3 2c-1.3 1-1.8 1.5-1.8 3" /><path d="M12 17h.01" /></>,
  sparkle: <path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5L12 3Z" />,
  bell: <><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  chevronRight: <path d="m9 18 6-6-6-6" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  arrowRight: <path d="M5 12h14m-6-6 6 6-6 6" />,
  spinner: <><path d="M12 3a9 9 0 1 0 9 9" /><path d="M12 3v4M21 12h-4" /></>,
};

export default function Icon({ name, className = "", title }) {
  return (
    <svg className={`svg-icon ${className}`.trim()} viewBox="0 0 24 24"
         fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round"
         aria-hidden={title ? undefined : "true"} role={title ? "img" : undefined}>
      {title && <title>{title}</title>}
      {paths[name] ?? paths.help}
    </svg>
  );
}
