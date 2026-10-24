/** Hand-drawn line icon set (24px grid, 1.6 stroke) used across the console. */

import type { SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 18, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconPulse = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12h3.5l2.2-6 3.4 12 2.4-7 1.7 4H21" />
  </Svg>
);

export const IconGallery = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <circle cx="8.5" cy="9.5" r="1.6" />
    <path d="m4.5 17 4.6-4.6a1.8 1.8 0 0 1 2.5 0L16 17" />
    <path d="m14 13.6 1.8-1.8a1.8 1.8 0 0 1 2.5 0L21 15" />
  </Svg>
);

export const IconSpark = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.2 13.9 9l5.8 1.9-5.8 1.9L12 18.6l-1.9-5.8L4.3 10.9 10.1 9Z" />
    <path d="M18.4 3.5v2.6M17.1 4.8h2.6" />
  </Svg>
);

export const IconChip = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="2.4" />
    <path d="M9.6 9.6h4.8v4.8H9.6z" />
    <path d="M9.8 3v2.4M14.2 3v2.4M9.8 18.6V21M14.2 18.6V21M3 9.8h2.4M3 14.2h2.4M18.6 9.8H21M18.6 14.2H21" />
  </Svg>
);

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10.8" cy="10.8" r="6.3" />
    <path d="m15.5 15.5 4.2 4.2" />
  </Svg>
);

export const IconCommand = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6.5a2.5 2.5 0 1 0-2.5 2.5H9m0 0V9m0-2.5h6M15 6.5a2.5 2.5 0 1 1 2.5 2.5H15m0 0V9m0 6v2.5m0-2.5h-6m0 0v2.5m0-2.5V9m0 6v2.5A2.5 2.5 0 1 1 6.5 15H9m6 0v2.5a2.5 2.5 0 1 0 2.5-2.5H15" />
  </Svg>
);

export const IconClose = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Svg>
);

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 9.5 6 6 6-6" />
  </Svg>
);

export const IconChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="m9.5 6 6 6-6 6" />
  </Svg>
);

export const IconChevronLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="m14.5 6-6 6 6 6" />
  </Svg>
);

export const IconArrowLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="M19 12H5.5M11 5.5 4.5 12l6.5 6.5" />
  </Svg>
);

export const IconArrowUpRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 17 17 7M8.5 7H17v8.5" />
  </Svg>
);

export const IconRefresh = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 12a8 8 0 1 1-2.4-5.7" />
    <path d="M20 4.5V9h-4.5" />
  </Svg>
);

export const IconRetry = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 12a7.5 7.5 0 0 1 12.9-5.2L20 9.5" />
    <path d="M20 4.8v4.7h-4.7" />
    <path d="M19.5 12a7.5 7.5 0 0 1-12.9 5.2L4 14.5" />
    <path d="M4 19.2v-4.7h4.7" />
  </Svg>
);

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 7h15M9.5 7V5.2a1.4 1.4 0 0 1 1.4-1.4h2.2a1.4 1.4 0 0 1 1.4 1.4V7" />
    <path d="M6.5 7 7.4 19a1.6 1.6 0 0 0 1.6 1.5h6a1.6 1.6 0 0 0 1.6-1.5L17.5 7" />
    <path d="M10.3 10.6v6.4M13.7 10.6v6.4" />
  </Svg>
);

export const IconDownload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.8v10.4M7.6 10.2 12 14.6l4.4-4.4" />
    <path d="M4.5 17.2v1.6a1.6 1.6 0 0 0 1.6 1.6h11.8a1.6 1.6 0 0 0 1.6-1.6v-1.6" />
  </Svg>
);

export const IconUpload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20.2V9.8M7.6 13.8 12 9.4l4.4 4.4" />
    <path d="M4.5 6.8V5.2A1.6 1.6 0 0 1 6.1 3.6h11.8a1.6 1.6 0 0 1 1.6 1.6v1.6" />
  </Svg>
);

export const IconCopy = (p: IconProps) => (
  <Svg {...p}>
    <rect x="8.5" y="8.5" width="11" height="11" rx="2.2" />
    <path d="M15.5 5.5H6.7A2.2 2.2 0 0 0 4.5 7.7v8.8" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="m4.8 12.6 4.6 4.6 9.8-10.4" />
  </Svg>
);

export const IconAlert = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.8 21 19.4H3Z" />
    <path d="M12 9.6v4.4M12 16.9v.2" />
  </Svg>
);

export const IconClock = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.2" />
    <path d="M12 7.4V12l3.2 2" />
  </Svg>
);

export const IconStop = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6.2" y="6.2" width="11.6" height="11.6" rx="2.6" />
  </Svg>
);

export const IconPlay = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 5.4 18.4 12 8 18.6Z" />
  </Svg>
);

export const IconPause = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8.6 5.5v13M15.4 5.5v13" />
  </Svg>
);

export const IconImage = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2.4" />
    <circle cx="8.6" cy="9.4" r="1.5" />
    <path d="m4.6 17.4 4.4-4.4a1.7 1.7 0 0 1 2.4 0l2.6 2.6m1.4-1.4 1.6-1.6a1.7 1.7 0 0 1 2.4 0l1.4 1.4" />
  </Svg>
);

export const IconVideo = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="5.5" width="13" height="13" rx="2.4" />
    <path d="m16 10.6 4.4-2.6v8l-4.4-2.6" />
  </Svg>
);

export const IconAudio = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 10.4v3.2M7.6 7.4v9.2M11.2 4.6v14.8M14.8 8.2v7.6M18.4 10.4v3.2" />
  </Svg>
);

export const IconEdit = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 19.5h4l10-10a2.3 2.3 0 0 0-3.2-3.2l-10 10Z" />
    <path d="m14.2 7.4 2.9 2.9" />
  </Svg>
);

export const IconGrid = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4" y="4" width="7" height="7" rx="1.6" />
    <rect x="13" y="4" width="7" height="7" rx="1.6" />
    <rect x="4" y="13" width="7" height="7" rx="1.6" />
    <rect x="13" y="13" width="7" height="7" rx="1.6" />
  </Svg>
);

export const IconList = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8.5 6h11M8.5 12h11M8.5 18h11" />
    <path d="M4.4 6h.2M4.4 12h.2M4.4 18h.2" />
  </Svg>
);

export const IconFilter = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 5.6h16l-6.2 7.4v5.4l-3.6 1.8v-7.2Z" />
  </Svg>
);

export const IconSliders = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 6.5h6M14 6.5h5M5 12h10M18 12h1M5 17.5h3M11 17.5h8" />
    <circle cx="12.5" cy="6.5" r="1.8" />
    <circle cx="16.5" cy="12" r="1.8" />
    <circle cx="9.5" cy="17.5" r="1.8" />
  </Svg>
);

export const IconKeyboard = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="6.5" width="19" height="11" rx="2.2" />
    <path d="M6 10h.2M9 10h.2M12 10h.2M15 10h.2M18 10h.2M6 13.5h.2M9 13.5h.2M12 13.5h.2M15 13.5h.2M18 13.5h.2M8 16h8" />
  </Svg>
);

export const IconLogout = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 4.5H6.8A1.8 1.8 0 0 0 5 6.3v11.4a1.8 1.8 0 0 0 1.8 1.8H14" />
    <path d="M10.5 12H20M16.6 8.4 20.2 12l-3.6 3.6" />
  </Svg>
);

export const IconLock = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5" y="10.4" width="14" height="9.6" rx="2.4" />
    <path d="M8.2 10.4V7.6a3.8 3.8 0 0 1 7.6 0v2.8" />
    <path d="M12 14.4v1.8" />
  </Svg>
);

export const IconUser = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="8.4" r="3.6" />
    <path d="M5 20a7 7 0 0 1 14 0" />
  </Svg>
);

export const IconEye = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2.8 12S6.4 5.8 12 5.8 21.2 12 21.2 12 17.6 18.2 12 18.2 2.8 12 2.8 12Z" />
    <circle cx="12" cy="12" r="2.8" />
  </Svg>
);

export const IconEyeOff = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 4.5 20 19.5" />
    <path d="M9.6 6.2A9.4 9.4 0 0 1 12 5.8c5.6 0 9.2 6.2 9.2 6.2a16 16 0 0 1-2.7 3.4" />
    <path d="M6.4 8.1A16 16 0 0 0 2.8 12S6.4 18.2 12 18.2a9 9 0 0 0 3.4-.7" />
    <path d="M10.2 10.4a2.8 2.8 0 0 0 3.6 3.6" />
  </Svg>
);

export const IconExternal = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13.5 4.5h6v6" />
    <path d="M19.5 4.5 11 13" />
    <path d="M17.5 14v4.2a1.6 1.6 0 0 1-1.6 1.6H5.3a1.6 1.6 0 0 1-1.6-1.6V7.6A1.6 1.6 0 0 1 5.3 6H9.5" />
  </Svg>
);

export const IconCode = (p: IconProps) => (
  <Svg {...p}>
    <path d="m8.6 7.6-4.6 4.4 4.6 4.4M15.4 7.6l4.6 4.4-4.6 4.4M13.2 4.8l-2.4 14.4" />
  </Svg>
);

export const IconLayers = (p: IconProps) => (
  <Svg {...p}>
    <path d="m12 3.4 8.6 4.4L12 12.2 3.4 7.8Z" />
    <path d="m4.4 12 7.6 4 7.6-4M4.4 16.2l7.6 4 7.6-4" />
  </Svg>
);

export const IconBolt = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13.2 3 5.4 13.4h5.6L10.8 21l7.8-10.4h-5.6Z" />
  </Svg>
);

export const IconDatabase = (p: IconProps) => (
  <Svg {...p}>
    <ellipse cx="12" cy="6.2" rx="7.6" ry="2.8" />
    <path d="M4.4 6.2v11.6c0 1.5 3.4 2.8 7.6 2.8s7.6-1.3 7.6-2.8V6.2" />
    <path d="M4.4 12c0 1.5 3.4 2.8 7.6 2.8s7.6-1.3 7.6-2.8" />
  </Svg>
);

export const IconRoute = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="6" cy="6.5" r="2.4" />
    <circle cx="18" cy="17.5" r="2.4" />
    <path d="M8.4 6.5h5.2a3.2 3.2 0 0 1 3.2 3.2v1.6a3.2 3.2 0 0 1-3.2 3.2H8.6" />
  </Svg>
);

export const IconServer = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.4" y="4.2" width="17.2" height="6.6" rx="2" />
    <rect x="3.4" y="13.2" width="17.2" height="6.6" rx="2" />
    <path d="M6.8 7.5h.2M6.8 16.5h.2" />
  </Svg>
);

export const IconPlus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const IconMinus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14" />
  </Svg>
);

export const IconSort = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 5v14M4.6 8.4 8 5l3.4 3.4M16 19V5M12.6 15.6 16 19l3.4-3.4" />
  </Svg>
);

export const IconMore = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="6" cy="12" r="1.3" />
    <circle cx="12" cy="12" r="1.3" />
    <circle cx="18" cy="12" r="1.3" />
  </Svg>
);

export const IconGrip = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6h.2M15 6h.2M9 12h.2M15 12h.2M9 18h.2M15 18h.2" />
  </Svg>
);

export const IconTarget = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.2" />
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.6v2.6M12 18.8v2.6M2.6 12h2.6M18.8 12h2.6" />
  </Svg>
);

export const IconAperture = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M12 3.4 8.2 12l-3.8-6.6M20.6 12h-8.4M8.2 12l7.2 6.6M12 20.6 15.8 12l3.8 6.6" />
  </Svg>
);

export const IconInfo = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M12 10.8v5.4M12 7.9v.2" />
  </Svg>
);

export const IconSeed = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.6c3.6 2 6 5.2 6 8.8a6 6 0 0 1-12 0c0-3.6 2.4-6.8 6-8.8Z" />
    <path d="M9.4 13.4c1.6.6 3.4.2 4.6-1" />
  </Svg>
);

export const IconDice = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4" y="4" width="16" height="16" rx="3.4" />
    <path d="M8.4 8.4h.2M15.4 8.4h.2M12 12h.2M8.4 15.4h.2M15.4 15.4h.2" />
  </Svg>
);

export const IconExpand = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 4.5H4.5V9M15 4.5h4.5V9M9 19.5H4.5V15M15 19.5h4.5V15" />
  </Svg>
);

export const IconShrink = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 9H9V4.5M19.5 9H15V4.5M4.5 15H9v4.5M19.5 15H15v4.5" />
  </Svg>
);

export const IconWave = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12c1.6 0 2.4-3.4 3.6-3.4S8.2 15.4 9.4 15.4 11 8 12.2 8s1.6 6 2.8 6 1.4-4.6 2.6-4.6S19 12 21 12" />
  </Svg>
);

export const IconPalette = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.6a8.4 8.4 0 1 0 0 16.8c1.2 0 1.8-.8 1.8-1.8 0-1.2 1-2 2.2-2h1.6a2.8 2.8 0 0 0 2.8-2.8A8.4 8.4 0 0 0 12 3.6Z" />
    <path d="M7.6 10.4h.2M10.4 7.2h.2M14.6 7.4h.2M17.2 11h.2" />
  </Svg>
);

export const IconBook = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.2 5.2a1.8 1.8 0 0 1 1.8-1.8h4.2v15.4H6a1.8 1.8 0 0 0-1.8 1.8Z" />
    <path d="M19.8 5.2a1.8 1.8 0 0 0-1.8-1.8h-4.2v15.4H18a1.8 1.8 0 0 1 1.8 1.8Z" />
  </Svg>
);

export const IconTerminal = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.2" y="4.4" width="17.6" height="15.2" rx="2.4" />
    <path d="m7 9.4 2.6 2.6L7 14.6M12.6 15h4" />
  </Svg>
);

export const IconLogo = ({ size = 28, ...rest }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true" {...rest}>
    <circle cx="16" cy="16" r="12.4" stroke="url(#lg-ring)" strokeWidth="1.6" opacity="0.9" />
    <circle cx="16" cy="16" r="7.6" stroke="url(#lg-ring)" strokeWidth="1.2" opacity="0.6" />
    <circle cx="16" cy="16" r="2.6" fill="#f0b04a" />
    <path d="M16 3.6v3.2M16 25.2v3.2M3.6 16h3.2M25.2 16h3.2" stroke="#f0b04a" strokeWidth="1.2" strokeLinecap="round" />
    <defs>
      <linearGradient id="lg-ring" x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
        <stop stopColor="#f0b04a" />
        <stop offset="0.55" stopColor="#f9c46b" stopOpacity="0.7" />
        <stop offset="1" stopColor="#45d6c4" stopOpacity="0.8" />
      </linearGradient>
    </defs>
  </svg>
);
