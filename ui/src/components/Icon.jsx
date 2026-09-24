/* A hand-rolled icon set. Every glyph is a 24x24 stroked path on the same
   grid and the same 1.75 stroke weight, so icons sit together evenly without
   pulling in an icon package (and without a second network request). */

const PATHS = {
  logo: (
    <>
      <path d="M12 3.2 4.6 7.1v6.2c0 4.2 3.1 7.1 7.4 8.5 4.3-1.4 7.4-4.3 7.4-8.5V7.1Z" />
      <path d="M9.2 12.2h1.9l1 3 1.6-5 1 2h1.9" />
    </>
  ),
  grid: (
    <>
      <rect x="3" y="3" width="7.5" height="7.5" rx="2" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="2" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="2" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" />
    </>
  ),
  scan: (
    <>
      <path d="M3 8V5.5A2.5 2.5 0 0 1 5.5 3H8M16 3h2.5A2.5 2.5 0 0 1 21 5.5V8M21 16v2.5a2.5 2.5 0 0 1-2.5 2.5H16M8 21H5.5A2.5 2.5 0 0 1 3 18.5V16" />
      <circle cx="12" cy="12" r="3.1" />
    </>
  ),
  slides: (
    <>
      <rect x="3" y="4" width="18" height="13" rx="2.4" />
      <path d="M3 13.2l4.3-3.6 3.5 2.9 3.2-4.2L21 13.6M7.5 20.5h9" />
    </>
  ),
  chart: (
    <>
      <path d="M3.5 20.5h17" />
      <path d="M6.5 20.5v-6M11 20.5V7M15.5 20.5v-9M20 20.5V4" />
    </>
  ),
  clipboard: (
    <>
      <path d="M9 4.5H7.5A2.5 2.5 0 0 0 5 7v12a2.5 2.5 0 0 0 2.5 2.5h9A2.5 2.5 0 0 0 19 19V7a2.5 2.5 0 0 0-2.5-2.5H15" />
      <rect x="9" y="2.5" width="6" height="4" rx="1.4" />
      <path d="M8.8 12h6.4M8.8 16h4.2" />
    </>
  ),
  book: (
    <>
      <path d="M4 5.2A2.2 2.2 0 0 1 6.2 3H19v15.5H6.2A2.2 2.2 0 0 0 4 20.7Z" />
      <path d="M4 20.7A2.2 2.2 0 0 1 6.2 18.5H19V21H6.2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m20 20-4.2-4.2" />
    </>
  ),
  bell: (
    <>
      <path d="M18 8.8a6 6 0 1 0-12 0c0 5.2-2 6.7-2 6.7h16s-2-1.5-2-6.7Z" />
      <path d="M13.7 19a2 2 0 0 1-3.4 0" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
    </>
  ),
  moon: <path d="M20.5 14.2A8.6 8.6 0 0 1 9.8 3.5a8.6 8.6 0 1 0 10.7 10.7Z" />,
  logout: (
    <>
      <path d="M15 4.5h2.5A2.5 2.5 0 0 1 20 7v10a2.5 2.5 0 0 1-2.5 2.5H15" />
      <path d="M10.5 15.5 14 12l-3.5-3.5M14 12H4" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3.6" />
      <path d="M4.8 20.2a7.4 7.4 0 0 1 14.4 0" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="2.9" />
      <path d="M19.1 14.4a1.6 1.6 0 0 0 .32 1.76l.06.06a1.9 1.9 0 1 1-2.7 2.7l-.05-.06a1.6 1.6 0 0 0-1.77-.32 1.6 1.6 0 0 0-.97 1.47v.17a1.9 1.9 0 1 1-3.8 0v-.09a1.6 1.6 0 0 0-1.05-1.47 1.6 1.6 0 0 0-1.76.32l-.06.06a1.9 1.9 0 1 1-2.7-2.7l.06-.06a1.6 1.6 0 0 0 .32-1.76 1.6 1.6 0 0 0-1.47-.98h-.17a1.9 1.9 0 1 1 0-3.8h.09a1.6 1.6 0 0 0 1.47-1.05 1.6 1.6 0 0 0-.32-1.76l-.06-.06a1.9 1.9 0 1 1 2.7-2.7l.06.06a1.6 1.6 0 0 0 1.76.32h.08A1.6 1.6 0 0 0 10.03 4v-.17a1.9 1.9 0 1 1 3.8 0v.09a1.6 1.6 0 0 0 .97 1.47 1.6 1.6 0 0 0 1.77-.32l.05-.06a1.9 1.9 0 1 1 2.7 2.7l-.06.06a1.6 1.6 0 0 0-.32 1.76v.08a1.6 1.6 0 0 0 1.47.97h.17a1.9 1.9 0 1 1 0 3.8h-.09a1.6 1.6 0 0 0-1.47.97Z" />
    </>
  ),
  upload: (
    <>
      <path d="M20 15.5V18a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18v-2.5" />
      <path d="M8 8.2 12 4.2l4 4M12 4.5v11" />
    </>
  ),
  download: (
    <>
      <path d="M20 15.5V18a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18v-2.5" />
      <path d="M8 11.3 12 15.3l4-4M12 15V4" />
    </>
  ),
  check: <path d="m4.5 12.5 5 5 10-11" />,
  checkCircle: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12.2 2.7 2.7L16 9.4" />
    </>
  ),
  x: <path d="M6 6l12 12M18 6 6 18" />,
  alert: (
    <>
      <path d="M10.3 3.9 2.4 17.4A2 2 0 0 0 4.1 20.4h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9.4v4M12 17h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-4.5M12 8h.01" />
    </>
  ),
  chevronRight: <path d="m9.5 5.5 6.5 6.5-6.5 6.5" />,
  chevronDown: <path d="m5.5 9.5 6.5 6.5 6.5-6.5" />,
  arrowUp: <path d="M12 20V4.5M5.5 11 12 4.5 18.5 11" />,
  arrowDown: <path d="M12 4v15.5M5.5 13l6.5 6.5L18.5 13" />,
  arrowRight: <path d="M4 12h15.5M13 5.5l6.5 6.5-6.5 6.5" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  panelLeft: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2.6" />
      <path d="M9.5 4v16" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3.2 9.5h17.6M3.2 14.5h17.6" />
      <path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z" />
    </>
  ),
  chevronsLeft: <path d="m10.5 7-5 5 5 5M17 7l-5 5 5 5" />,
  chevronsRight: <path d="m13.5 7 5 5-5 5M7 7l5 5-5 5" />,
  layers: (
    <>
      <path d="m12 3 9 4.8-9 4.8-9-4.8Z" />
      <path d="m3.6 12.3 8.4 4.5 8.4-4.5M3.6 16.8l8.4 4.5 8.4-4.5" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 4.8 6.1v5.4c0 4.3 3 8.3 7.2 9.5 4.2-1.2 7.2-5.2 7.2-9.5V6.1Z" />
      <path d="m9 12 2.2 2.2L15.2 10" />
    </>
  ),
  activity: <path d="M3 12h4l2.5-7 5 14 2.5-7H21" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.2l3.3 2" />
    </>
  ),
  sparkles: (
    <>
      <path d="M11 3.5 12.6 8 17 9.6 12.6 11.2 11 15.7 9.4 11.2 5 9.6 9.4 8Z" />
      <path d="M18 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8Z" />
    </>
  ),
  file: (
    <>
      <path d="M13.5 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V8.5Z" />
      <path d="M13.5 3v5.5H19" />
    </>
  ),
  refresh: (
    <>
      <path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1" />
      <path d="M20.8 4.5v4.8H16" />
    </>
  ),
  lock: (
    <>
      <rect x="4.5" y="10" width="15" height="10.5" rx="2.4" />
      <path d="M8 10V7.5a4 4 0 0 1 8 0V10" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2.4" />
      <path d="m3.6 6.8 7.2 5.2a2 2 0 0 0 2.4 0l7.2-5.2" />
    </>
  ),
  pen: (
    <>
      <path d="M16.9 3.7a2.1 2.1 0 0 1 3 3L8.4 18.2l-4.1 1.1 1.1-4.1Z" />
      <path d="m14.4 6.2 3.4 3.4" />
    </>
  ),
  eyeOff: (
    <>
      <path d="M10.6 6.2A8.9 8.9 0 0 1 12 6c6 0 9.5 6 9.5 6a17 17 0 0 1-3 3.7M6.4 7.8A17 17 0 0 0 2.5 12S6 18 12 18a8.8 8.8 0 0 0 3.4-.66" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" />
    </>
  ),
};

export default function Icon({ name, size = 18, strokeWidth = 1.75, ...rest }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {path}
    </svg>
  );
}
