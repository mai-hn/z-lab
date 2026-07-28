type IconProps = { size?: number; className?: string };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export function DriveIcon({ size = 22, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 8.5h16l-2 11H6l-2-11Z" />
      <path d="m7 8.5 2-4h6l2 4M9 15h6" />
    </svg>
  );
}

export function RouteIcon({ size = 22, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="6" cy="5" r="2" />
      <circle cx="18" cy="19" r="2" />
      <path d="M6 7v3c0 2 1 3 3 3h6c2 0 3 1 3 3v1M12 5h6M15 2l3 3-3 3" />
    </svg>
  );
}

export function ModelIcon({ size = 22, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M9 9h6v6H9zM9 1v3m6-3v3M9 20v3m6-3v3M1 9h3m-3 6h3m16-6h3m-3 6h3" />
    </svg>
  );
}

export function ArrowIcon({ size = 20, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M5 12h14m-5-5 5 5-5 5" />
    </svg>
  );
}

export function UploadIcon({ size = 20, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 16V4m-4 4 4-4 4 4M5 20h14" />
    </svg>
  );
}

export function FolderIcon({ size = 20, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M3 6h7l2 2h9v11H3z" />
    </svg>
  );
}

export function FileIcon({ size = 20, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 2h8l4 4v16H6zM14 2v5h5" />
    </svg>
  );
}

export function TrashIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7m4 4v6m4-6v6" />
    </svg>
  );
}

export function RefreshIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M18.5 9A7 7 0 0 0 6 6.5L4 9m2 6a7 7 0 0 0 12 2.5L20 15" />
    </svg>
  );
}

export function PlusIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function CheckIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="m5 12 4 4L19 6" />
    </svg>
  );
}

export function DownloadIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 4v12m-5-5 5 5 5-5M5 20h14" />
    </svg>
  );
}

export function SettingsIcon({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />
    </svg>
  );
}
