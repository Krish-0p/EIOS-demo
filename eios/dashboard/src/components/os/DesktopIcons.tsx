import React from "react";

export type WindowId =
  | "filesystem"
  | "terminal"
  | "systemmonitor"
  | "processes"
  | "ai"
  | "workflows"
  | "integrations"
  | "security"
  | "reports"
  | "settings"
  | "recycle";

interface DesktopIconsProps {
  activeWindows: Record<WindowId, boolean>;
  onToggleWindow: (id: WindowId) => void;
}

// 1. Realistic Hardware Terminal Console
function TerminalRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Monitor chassis base shadow */}
      <rect x="5" y="7" width="38" height="32" rx="5" fill="#011428" />
      {/* Outer beveled bezel */}
      <rect x="4" y="6" width="40" height="32" rx="4" fill="url(#term-bezel)" stroke="#26658C" strokeWidth="1" />
      {/* Inner dark CRT glass screen */}
      <rect x="7" y="11" width="34" height="24" rx="2" fill="#010812" stroke="#0a2a44" strokeWidth="0.8" />
      {/* Titlebar controls */}
      <circle cx="10" cy="8.5" r="1.5" fill="#E04A5F" />
      <circle cx="14" cy="8.5" r="1.5" fill="#F08A7C" />
      <circle cx="18" cy="8.5" r="1.5" fill="#54ACBF" />
      {/* Shell prompt text `>_` */}
      <path d="M11 16L16 20L11 24" stroke="#54ACBF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="18" y1="24" x2="25" y2="24" stroke="#A7EBF2" strokeWidth="2" strokeLinecap="round" />
      {/* Screen scanline reflection */}
      <path d="M7 11L41 11L25 35L7 35Z" fill="white" fillOpacity="0.03" />
      {/* Stand foot */}
      <path d="M19 38L17 43H31L29 38H19Z" fill="#0a2842" stroke="#26658C" strokeWidth="0.8" />
      <defs>
        <linearGradient id="term-bezel" x1="4" y1="6" x2="4" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0b304f" />
          <stop offset="1" stopColor="#03182b" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 2. Realistic 3D Leather/Executive File System Folder
function FolderRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Back tab */}
      <path d="M6 14C6 12.3431 7.34315 11 9 11H18L22 15H39C40.6569 15 42 16.3431 42 18V36C42 37.6569 40.6569 39 39 39H9C7.34315 39 6 37.6569 6 36V14Z" fill="#023859" stroke="#26658C" strokeWidth="1" />
      {/* Paper sheets inside folder */}
      <rect x="10" y="13" width="28" height="14" rx="1.5" fill="#E8F4F8" />
      <line x1="13" y1="16" x2="25" y2="16" stroke="#26658C" strokeWidth="1" strokeLinecap="round" />
      <line x1="13" y1="19" x2="33" y2="19" stroke="#54ACBF" strokeWidth="1" strokeLinecap="round" />
      {/* Front flap with 3D perspective & metallic tab */}
      <path d="M5 20C5 18.8954 5.89543 18 7 18H41C42.1046 18 43 18.8954 43 20L41 37C41 38.6569 39.6569 40 38 40H8C6.34315 40 5 38.6569 5 37L5 20Z" fill="url(#folder-front)" stroke="#54ACBF" strokeWidth="1" />
      {/* Folder crease highlight */}
      <line x1="6" y1="21" x2="42" y2="21" stroke="#A7EBF2" strokeOpacity="0.4" strokeWidth="1" />
      {/* Folder center badge */}
      <rect x="20" y="27" width="8" height="4" rx="1" fill="#011C40" stroke="#A7EBF2" strokeWidth="0.8" />
      <defs>
        <linearGradient id="folder-front" x1="5" y1="18" x2="41" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="#125178" />
          <stop offset="1" stopColor="#032b47" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 3. Realistic Hardware Telemetry Oscilloscope / Process Monitor
function ProcessRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Heavy circular instrument bezel */}
      <circle cx="24" cy="24" r="20" fill="url(#inst-bezel)" stroke="#26658C" strokeWidth="1.5" />
      {/* Inner dial rim */}
      <circle cx="24" cy="24" r="16.5" fill="#010e1c" stroke="#062238" strokeWidth="1" />
      {/* Precision measurement grid */}
      <line x1="10" y1="24" x2="38" y2="24" stroke="#0d3c61" strokeWidth="0.8" strokeDasharray="2 2" />
      <line x1="24" y1="10" x2="24" y2="38" stroke="#0d3c61" strokeWidth="0.8" strokeDasharray="2 2" />
      <circle cx="24" cy="24" r="10" stroke="#0d3c61" strokeWidth="0.8" strokeDasharray="2 2" />
      {/* Realistic solid ECG wave */}
      <path d="M9 24H16L19 18L22 30L26 14L29 27L32 22L34 24H39" stroke="#54ACBF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {/* Active pulse marker */}
      <circle cx="26" cy="14" r="2" fill="#A7EBF2" />
      {/* Instrument screws */}
      <circle cx="7" cy="7" r="1" fill="#54ACBF" />
      <circle cx="41" cy="7" r="1" fill="#54ACBF" />
      <circle cx="7" cy="41" r="1" fill="#54ACBF" />
      <circle cx="41" cy="41" r="1" fill="#54ACBF" />
      <defs>
        <linearGradient id="inst-bezel" x1="6" y1="6" x2="42" y2="42" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0a3252" />
          <stop offset="1" stopColor="#021424" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 4. Realistic Solid Neural Microprocessor Chip (AI Assistant)
function AIRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Copper/Gold connector pins along edges */}
      {/* Top pins */}
      <rect x="14" y="3" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="19" y="3" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="24" y="3" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="29" y="3" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="34" y="3" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      {/* Bottom pins */}
      <rect x="14" y="41" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="19" y="41" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="24" y="41" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="29" y="41" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      <rect x="34" y="41" width="2" height="4" rx="0.5" fill="#FCD2B3" />
      {/* Left pins */}
      <rect x="3" y="14" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="3" y="19" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="3" y="24" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="3" y="29" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="3" y="34" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      {/* Right pins */}
      <rect x="41" y="14" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="41" y="19" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="41" y="24" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="41" y="29" width="4" height="2" rx="0.5" fill="#FCD2B3" />
      <rect x="41" y="34" width="4" height="2" rx="0.5" fill="#FCD2B3" />

      {/* Ceramic dark substrate chip */}
      <rect x="7" y="7" width="34" height="34" rx="4" fill="url(#chip-surface)" stroke="#26658C" strokeWidth="1.2" />
      {/* Laser-etched silicon core */}
      <rect x="13" y="13" width="22" height="22" rx="2.5" fill="#011428" stroke="#54ACBF" strokeWidth="1" />
      {/* Neural node matrix */}
      <circle cx="18" cy="18" r="1.5" fill="#A7EBF2" />
      <circle cx="30" cy="18" r="1.5" fill="#A7EBF2" />
      <circle cx="24" cy="24" r="2.2" fill="#54ACBF" />
      <circle cx="18" cy="30" r="1.5" fill="#A7EBF2" />
      <circle cx="30" cy="30" r="1.5" fill="#A7EBF2" />
      {/* Bus connections */}
      <line x1="18" y1="18" x2="24" y2="24" stroke="#54ACBF" strokeWidth="1.2" />
      <line x1="30" y1="18" x2="24" y2="24" stroke="#54ACBF" strokeWidth="1.2" />
      <line x1="18" y1="30" x2="24" y2="24" stroke="#54ACBF" strokeWidth="1.2" />
      <line x1="30" y1="30" x2="24" y2="24" stroke="#54ACBF" strokeWidth="1.2" />
      <defs>
        <linearGradient id="chip-surface" x1="7" y1="7" x2="41" y2="41" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0c2f4d" />
          <stop offset="1" stopColor="#021526" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 5. Realistic Machined Gears & Conduits (Workflow Engine)
function WorkflowRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Back conduit pipe */}
      <path d="M12 36L24 24L36 36" stroke="#023859" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      {/* Large solid steel gear */}
      <g transform="translate(18, 18)">
        <circle cx="0" cy="0" r="11" fill="url(#gear-grad)" stroke="#26658C" strokeWidth="1" />
        {/* Teeth */}
        {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
          <rect
            key={angle}
            x="-2"
            y="-14"
            width="4"
            height="4"
            rx="0.8"
            fill="#26658C"
            transform={`rotate(${angle} 0 0)`}
          />
        ))}
        {/* Gear center hole with bolt */}
        <circle cx="0" cy="0" r="5" fill="#010e1c" stroke="#54ACBF" strokeWidth="1" />
        <circle cx="0" cy="0" r="2" fill="#A7EBF2" />
      </g>
      {/* Interlocking smaller copper gear */}
      <g transform="translate(34, 30)">
        <circle cx="0" cy="0" r="7" fill="url(#gear-copper)" stroke="#F08A7C" strokeWidth="0.8" />
        {[0, 60, 120, 180, 240, 300].map((angle) => (
          <rect
            key={angle}
            x="-1.5"
            y="-9"
            width="3"
            height="2.5"
            rx="0.5"
            fill="#F08A7C"
            transform={`rotate(${angle} 0 0)`}
          />
        ))}
        <circle cx="0" cy="0" r="3" fill="#010e1c" stroke="#FCD2B3" strokeWidth="0.8" />
      </g>
      <defs>
        <linearGradient id="gear-grad" x1="-11" y1="-11" x2="11" y2="11" gradientUnits="userSpaceOnUse">
          <stop stopColor="#175079" />
          <stop offset="1" stopColor="#042036" />
        </linearGradient>
        <linearGradient id="gear-copper" x1="-7" y1="-7" x2="7" y2="7" gradientUnits="userSpaceOnUse">
          <stop stopColor="#9c4c40" />
          <stop offset="1" stopColor="#4d1a14" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 6. Realistic Telemetry Multi-Bar Meter Deck (System Monitor)
function SystemMonitorRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Instrument enclosure chassis */}
      <rect x="5" y="7" width="38" height="34" rx="4" fill="url(#meter-deck)" stroke="#26658C" strokeWidth="1.2" />
      {/* Inner display bezel */}
      <rect x="8" y="10" width="32" height="28" rx="2" fill="#010e1c" stroke="#05243d" strokeWidth="0.8" />
      {/* Realistic Solid LED Meter Bars */}
      {/* Bar 1: Green/Teal */}
      <rect x="12" y="28" width="4" height="7" rx="0.8" fill="#1C5147" />
      <rect x="12" y="23" width="4" height="4" rx="0.8" fill="#6EAA90" />
      <rect x="12" y="18" width="4" height="4" rx="0.8" fill="#B5E3C8" />
      {/* Bar 2: Blue/Cyan */}
      <rect x="18" y="28" width="4" height="7" rx="0.8" fill="#023859" />
      <rect x="18" y="23" width="4" height="4" rx="0.8" fill="#26658C" />
      <rect x="18" y="18" width="4" height="4" rx="0.8" fill="#54ACBF" />
      <rect x="18" y="13" width="4" height="4" rx="0.8" fill="#A7EBF2" />
      {/* Bar 3: Cyan */}
      <rect x="24" y="28" width="4" height="7" rx="0.8" fill="#023859" />
      <rect x="24" y="23" width="4" height="4" rx="0.8" fill="#26658C" />
      <rect x="24" y="18" width="4" height="4" rx="0.8" fill="#54ACBF" />
      {/* Bar 4: Coral warning peak */}
      <rect x="30" y="28" width="4" height="7" rx="0.8" fill="#023859" />
      <rect x="30" y="23" width="4" height="4" rx="0.8" fill="#26658C" />
      <rect x="30" y="18" width="4" height="4" rx="0.8" fill="#F08A7C" />
      <rect x="30" y="13" width="4" height="4" rx="0.8" fill="#E04A5F" />
      {/* Tick markers */}
      <line x1="36" y1="15" x2="38" y2="15" stroke="#54ACBF" strokeWidth="0.8" />
      <line x1="36" y1="20" x2="38" y2="20" stroke="#54ACBF" strokeWidth="0.8" />
      <line x1="36" y1="25" x2="38" y2="25" stroke="#54ACBF" strokeWidth="0.8" />
      <line x1="36" y1="30" x2="38" y2="30" stroke="#54ACBF" strokeWidth="0.8" />
      <defs>
        <linearGradient id="meter-deck" x1="5" y1="7" x2="43" y2="41" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0b3252" />
          <stop offset="1" stopColor="#021424" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 7. Realistic 1U Network Switch / Fiber Center (Integration Center)
function IntegrationsRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Rackmount switch unit */}
      <rect x="4" y="12" width="40" height="24" rx="3" fill="url(#switch-body)" stroke="#26658C" strokeWidth="1" />
      {/* Rack ears with mounting holes */}
      <rect x="4" y="12" width="4" height="24" fill="#021e36" />
      <rect x="40" y="12" width="4" height="24" fill="#021e36" />
      <circle cx="6" cy="18" r="1.2" fill="#54ACBF" />
      <circle cx="6" cy="30" r="1.2" fill="#54ACBF" />
      <circle cx="42" cy="18" r="1.2" fill="#54ACBF" />
      <circle cx="42" cy="30" r="1.2" fill="#54ACBF" />
      {/* RJ45 Ethernet ports with gold contacts */}
      {[12, 19, 26, 33].map((x) => (
        <g key={x}>
          <rect x={x} y="18" width="5" height="6" rx="0.5" fill="#010a14" stroke="#0a3252" strokeWidth="0.8" />
          <line x1={x + 1.2} y1="19" x2={x + 3.8} y2="19" stroke="#FCD2B3" strokeWidth="0.8" />
          {/* Link activity LED */}
          <circle cx={x + 2.5} cy="27" r="1" fill={x === 33 ? "#F08A7C" : "#54ACBF"} />
        </g>
      ))}
      {/* Fiber patch connector cable loop */}
      <path d="M14 24C14 36 28 38 35 24" stroke="#A7EBF2" strokeWidth="1.5" strokeLinecap="round" />
      <defs>
        <linearGradient id="switch-body" x1="4" y1="12" x2="44" y2="36" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0d3557" />
          <stop offset="1" stopColor="#02182b" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 8. Realistic Heavy Stainless Steel Heraldic Shield (Security Center)
function SecurityRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Heavy metallic shield body */}
      <path d="M24 6L39 12V24C39 33.5 32.5 40 24 43C15.5 40 9 33.5 9 24V12L24 6Z" fill="url(#shield-body)" stroke="#54ACBF" strokeWidth="1.5" strokeLinejoin="round" />
      {/* Inner beveled rim */}
      <path d="M24 9L36 14V23C36 31 31 36.5 24 39.5C17 36.5 12 31 12 23V14L24 9Z" fill="#021e33" stroke="#26658C" strokeWidth="1" />
      {/* Central steel reinforcement cross */}
      <line x1="24" y1="10" x2="24" y2="38" stroke="#26658C" strokeWidth="2" strokeOpacity="0.5" />
      <line x1="13" y1="22" x2="35" y2="22" stroke="#26658C" strokeWidth="2" strokeOpacity="0.5" />
      {/* Solid green security check crest */}
      <path d="M18 23L22 27L30 18" stroke="#B5E3C8" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {/* Highlight reflection */}
      <path d="M24 9L36 14V23C36 27 34 31 32 34L24 9Z" fill="white" fillOpacity="0.08" />
      <defs>
        <linearGradient id="shield-body" x1="9" y1="6" x2="39" y2="43" gradientUnits="userSpaceOnUse">
          <stop stopColor="#1d5c8a" />
          <stop offset="1" stopColor="#031b2e" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 9. Realistic Executive Leather Binder / Audit Report (Reports)
function ReportsRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Leather portfolio binder cover */}
      <rect x="7" y="6" width="34" height="36" rx="3" fill="url(#binder-cover)" stroke="#26658C" strokeWidth="1" />
      {/* Paper document sheet */}
      <rect x="11" y="9" width="26" height="30" rx="1.5" fill="#EBF4F7" />
      {/* Metallic binder clip at top */}
      <rect x="18" y="7" width="12" height="4" rx="1" fill="#26658C" stroke="#A7EBF2" strokeWidth="0.8" />
      {/* Printed data metrics & bar chart on page */}
      <line x1="14" y1="15" x2="28" y2="15" stroke="#023859" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="14" y1="18" x2="22" y2="18" stroke="#54ACBF" strokeWidth="1" strokeLinecap="round" />
      {/* Miniature colored bar chart on document */}
      <rect x="14" y="29" width="3" height="6" fill="#023859" rx="0.5" />
      <rect x="19" y="26" width="3" height="9" fill="#26658C" rx="0.5" />
      <rect x="24" y="22" width="3" height="13" fill="#54ACBF" rx="0.5" />
      <rect x="29" y="25" width="3" height="10" fill="#E04A5F" rx="0.5" />
      <line x1="13" y1="36" x2="34" y2="36" stroke="#26658C" strokeWidth="0.8" />
      <defs>
        <linearGradient id="binder-cover" x1="7" y1="6" x2="41" y2="42" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0d3557" />
          <stop offset="1" stopColor="#011629" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 10. Realistic Heavy Steel Mechanic Cogwheel (Settings)
function SettingsRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      <g transform="translate(24, 24)">
        {/* Outer heavy bevel ring */}
        <circle cx="0" cy="0" r="16" fill="url(#cog-bezel)" stroke="#26658C" strokeWidth="1.2" />
        {/* 8 Precision-cut gear teeth */}
        {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
          <rect
            key={angle}
            x="-3.5"
            y="-20"
            width="7"
            height="6"
            rx="1"
            fill="#26658C"
            stroke="#54ACBF"
            strokeWidth="0.8"
            transform={`rotate(${angle} 0 0)`}
          />
        ))}
        {/* Recessed hub face */}
        <circle cx="0" cy="0" r="11" fill="#011221" stroke="#0c375c" strokeWidth="1" />
        {/* Hexagonal central steel bolt */}
        <path d="M0 -6L5.2 -3V3L0 6L-5.2 3V-3L0 -6Z" fill="#54ACBF" stroke="#A7EBF2" strokeWidth="0.8" />
        <circle cx="0" cy="0" r="2.2" fill="#010e1a" />
      </g>
      <defs>
        <linearGradient id="cog-bezel" x1="-16" y1="-16" x2="16" y2="16" gradientUnits="userSpaceOnUse">
          <stop stopColor="#1b547d" />
          <stop offset="1" stopColor="#031a2e" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// 11. Realistic Stainless Steel Mesh Wastebasket (Recycle Bin)
function RecycleRealisticIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-10 w-10 drop-shadow-md" fill="none">
      {/* Crumpled paper inside basket */}
      <path d="M19 14L22 9L27 12L31 8L33 14H19Z" fill="#E8F4F8" stroke="#54ACBF" strokeWidth="0.8" />
      <line x1="22" y1="11" x2="28" y2="11" stroke="#26658C" strokeWidth="0.8" />
      {/* Top stainless steel rim */}
      <ellipse cx="24" cy="14" rx="16" ry="3.5" fill="#1b4b70" stroke="#54ACBF" strokeWidth="1.2" />
      {/* Basket tapered body */}
      <path d="M9 14L13 38C13.5 40 17 41.5 24 41.5C31 41.5 34.5 40 35 38L39 14" fill="url(#basket-body)" stroke="#26658C" strokeWidth="1" />
      {/* Wire mesh texture lines */}
      <line x1="14" y1="18" x2="34" y2="18" stroke="#54ACBF" strokeOpacity="0.4" strokeWidth="0.8" />
      <line x1="15" y1="24" x2="33" y2="24" stroke="#54ACBF" strokeOpacity="0.4" strokeWidth="0.8" />
      <line x1="16" y1="30" x2="32" y2="30" stroke="#54ACBF" strokeOpacity="0.4" strokeWidth="0.8" />
      <line x1="17" y1="35" x2="31" y2="35" stroke="#54ACBF" strokeOpacity="0.4" strokeWidth="0.8" />
      {/* Vertical crosshatch struts */}
      <line x1="19" y1="16" x2="20" y2="39" stroke="#54ACBF" strokeOpacity="0.4" strokeWidth="0.8" />
      <line x1="24" y1="16" x2="24" y2="40" stroke="#54ACBF" strokeOpacity="0.4" strokeWidth="0.8" />
      <line x1="29" y1="16" x2="28" y2="39" stroke="#54ACBF" strokeOpacity="0.4" strokeWidth="0.8" />
      {/* Base ellipse */}
      <ellipse cx="24" cy="38" rx="10" ry="2.5" fill="#011221" stroke="#26658C" strokeWidth="0.8" />
      <defs>
        <linearGradient id="basket-body" x1="9" y1="14" x2="39" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0d3557" />
          <stop offset="1" stopColor="#011424" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export function DesktopIcons({ activeWindows, onToggleWindow }: DesktopIconsProps) {
  const icons: {
    id: WindowId;
    label: string;
    renderIcon: () => React.ReactNode;
  }[] = [
    {
      id: "terminal",
      label: "EIOS Terminal",
      renderIcon: () => <TerminalRealisticIcon />,
    },
    {
      id: "filesystem",
      label: "File System",
      renderIcon: () => <FolderRealisticIcon />,
    },
    {
      id: "processes",
      label: "Process Monitor",
      renderIcon: () => <ProcessRealisticIcon />,
    },
    {
      id: "ai",
      label: "AI Assistant",
      renderIcon: () => <AIRealisticIcon />,
    },
    {
      id: "workflows",
      label: "Workflow Engine",
      renderIcon: () => <WorkflowRealisticIcon />,
    },
    {
      id: "systemmonitor",
      label: "System Monitor",
      renderIcon: () => <SystemMonitorRealisticIcon />,
    },
    {
      id: "integrations",
      label: "Integration Center",
      renderIcon: () => <IntegrationsRealisticIcon />,
    },
    {
      id: "security",
      label: "Security Center",
      renderIcon: () => <SecurityRealisticIcon />,
    },
    {
      id: "reports",
      label: "Reports",
      renderIcon: () => <ReportsRealisticIcon />,
    },
    {
      id: "settings",
      label: "Settings",
      renderIcon: () => <SettingsRealisticIcon />,
    },
    {
      id: "recycle",
      label: "Recycle Bin",
      renderIcon: () => <RecycleRealisticIcon />,
    },
  ];

  return (
    <aside className="relative z-20 flex w-[90px] flex-col items-center gap-1.5 py-2.5 select-none overflow-y-auto scrollbar-themed border-r border-[rgb(var(--eios-0d2e49))]/60 bg-[rgb(var(--eios-010610))]/70">
      {icons.filter(item => item.id !== 'recycle').map((item) => {
        const isOpen = activeWindows[item.id];

        return (
          <button
            key={item.id}
            onClick={() => onToggleWindow(item.id)}
            className={`group relative flex w-[82px] flex-col items-center rounded-xl p-1.5 transition-all duration-150 hover:bg-[rgb(var(--eios-021f36))]/60 active:scale-95 ${
              isOpen ? "bg-[rgb(var(--eios-02243d))]/80 border border-[rgb(var(--eios-26658c))]" : "border border-transparent"
            }`}
          >
            {/* Realistic Solid Icon Canvas */}
            <div className="relative flex h-11 w-11 items-center justify-center transition-transform duration-150 group-hover:scale-105">
              {item.renderIcon()}
            </div>

            {/* Label below icon with high contrast crisp typography */}
            <span className="mt-1 w-full text-center font-display text-[9px] font-semibold text-[rgb(var(--eios-text-slate-200))] leading-tight group-hover:text-[rgb(var(--eios-a7ebf2))]">
              {item.label}
            </span>

            {/* Active window indicator pill (Clean solid dot, zero neon glow) */}
            {isOpen && (
              <span className="absolute bottom-0.5 h-1 w-3 rounded-full bg-[rgb(var(--eios-54acbf))]" />
            )}
          </button>
        );
      })}
    </aside>
  );
}
