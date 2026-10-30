/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/hooks/**/*.{js,ts,jsx,tsx}",
    "./src/lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      colors: {
        gray: {
          925: "#0d1117",
          950: "#0a0e17",
        },
        qa: {
          bg: "var(--qa-bg)",
          panel: "var(--qa-panel)",
          "panel-secondary": "var(--qa-panel-secondary)",
          border: "var(--qa-border)",
          "border-strong": "var(--qa-border-strong)",
          text: "var(--qa-text)",
          muted: "var(--qa-text-secondary)",
          accent: "var(--qa-accent)",
          "accent-dim": "var(--qa-accent-dim)",
          gain: "var(--qa-gain)",
          loss: "var(--qa-loss)",
          "success-bg": "var(--qa-success-bg)",
          "danger-bg": "var(--qa-danger-bg)",
          "success-border": "var(--qa-success-border)",
          "danger-border": "var(--qa-danger-border)",
          warning: "var(--qa-warning-text)",
          "on-accent": "var(--qa-on-accent)",
        },
        cockpit: {
          bg: "var(--cockpit-bg)",
          surface: "var(--cockpit-surface)",
          panel: "var(--cockpit-panel)",
          "panel-raised": "var(--cockpit-panel-raised)",
          border: "var(--cockpit-border)",
          "border-strong": "var(--cockpit-border-strong)",
        },
        status: {
          ok: "var(--status-ok)",
          caution: "var(--status-caution)",
          block: "var(--status-block)",
          none: "var(--status-none)",
        },
        primary: "var(--color-primary)",
        accent: "var(--color-accent)",
        terminal: {
          bg: "var(--terminal-bg)",
          surface: "var(--terminal-surface)",
          panel: "var(--terminal-panel)",
          "panel-raised": "var(--terminal-panel-raised)",
          border: "var(--terminal-border)",
          "border-strong": "var(--terminal-border-strong)",
          accent: "var(--terminal-accent)",
          "accent-dim": "var(--terminal-accent-dim)",
          "accent-muted": "var(--terminal-accent-muted)",
          muted: "var(--terminal-muted)",
          text: "var(--terminal-text)",
          up: "var(--terminal-up)",
          down: "var(--terminal-down)",
        },
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.2s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      borderRadius: {
        xl: "0.75rem",
        "2xl": "1rem",
      },
      boxShadow: {
        dark: "none",
        glow: "0 0 0 1px rgba(245, 166, 35, 0.2)",
      },
      transitionDuration: {
        DEFAULT: "200ms",
      },
    },
  },
  plugins: [],
};
