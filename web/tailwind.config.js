/** @type {import('tailwindcss').Config} */

// "Darkroom" palette. Every colour used by the console is declared here so the
// whole look can be retuned from one place. Values are chosen for contrast on
// the ink surfaces: body text stays >= 7:1, secondary text >= 4.5:1.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#06070a",
          900: "#0a0c11",
          850: "#0f1218",
          800: "#141821",
          750: "#191e28",
          700: "#20262f",
          650: "#29303b",
          600: "#343c48",
        },
        amber: {
          50: "#fff8ec",
          100: "#ffefd0",
          200: "#ffdca1",
          300: "#f9c46b",
          400: "#f0b04a",
          500: "#e29a2f",
          600: "#c47d1a",
          700: "#9a5f12",
        },
        jade: {
          300: "#6fe8d3",
          400: "#45d6c4",
          500: "#23b8a6",
          600: "#128d7f",
        },
        coral: {
          300: "#ff9aa9",
          400: "#ff6b81",
          500: "#ef4b65",
          600: "#c73350",
        },
        azure: {
          300: "#8fc2ff",
          400: "#5aa8ff",
          500: "#3d8ef5",
          600: "#2a6fc9",
        },
        violet: {
          300: "#c4b0ff",
          400: "#a68cff",
          500: "#8a6cf0",
        },
        fg: {
          100: "#f6f2e9",
          200: "#e6e2d8",
          300: "#c6c2b8",
          400: "#a3a0a0",
          500: "#7f7d82",
          600: "#5f5e66",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "Segoe UI",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "Cascadia Code", "SFMono-Regular", "Consolas", "monospace"],
        display: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
      },
      borderRadius: {
        xl2: "1.125rem",
      },
      boxShadow: {
        glass: "inset 0 1px 0 0 rgba(255,255,255,0.06), 0 24px 60px -32px rgba(0,0,0,0.9)",
        print: "0 40px 80px -40px rgba(0,0,0,0.95), 0 0 0 1px rgba(255,255,255,0.06)",
        lift: "0 18px 40px -24px rgba(0,0,0,0.85)",
        glow: "0 0 0 1px rgba(240,176,74,0.35), 0 8px 30px -12px rgba(240,176,74,0.35)",
      },
      backgroundImage: {
        safelight:
          "radial-gradient(120% 80% at 15% -10%, rgba(240,176,74,0.16) 0%, rgba(240,176,74,0) 55%)",
        "safelight-teal":
          "radial-gradient(120% 80% at 85% 0%, rgba(69,214,196,0.10) 0%, rgba(69,214,196,0) 55%)",
        "grid-faint":
          "linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)",
        sheen: "linear-gradient(100deg, transparent 20%, rgba(255,255,255,0.10) 50%, transparent 80%)",
      },
      backgroundSize: {
        grid: "28px 28px",
      },
      transitionTimingFunction: {
        dark: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.97)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        pulseRing: {
          "0%": { boxShadow: "0 0 0 0 rgba(69,214,196,0.45)" },
          "70%": { boxShadow: "0 0 0 8px rgba(69,214,196,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(69,214,196,0)" },
        },
        breathe: {
          "0%, 100%": { opacity: "0.55" },
          "50%": { opacity: "1" },
        },
        slideRight: {
          from: { transform: "translateX(16px)", opacity: "0" },
          to: { transform: "translateX(0)", opacity: "1" },
        },
        spin: {
          to: { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "fade-up": "fade-up 220ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "fade-in": "fade-in 160ms ease-out both",
        "scale-in": "scale-in 180ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        shimmer: "shimmer 1.6s linear infinite",
        "pulse-ring": "pulseRing 2.4s ease-out infinite",
        breathe: "breathe 3.2s ease-in-out infinite",
        "slide-right": "slideRight 200ms cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "spin-slow": "spin 1.6s linear infinite",
      },
    },
  },
  plugins: [],
};
