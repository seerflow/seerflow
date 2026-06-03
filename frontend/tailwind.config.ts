import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  // Dark is the default; light is .sf-light on <html>.
  // No Tailwind dark: variants needed — colors come from CSS vars that flip.
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        /* ── Brand tokens — direct var() refs (vars hold complete oklch values) */
        bg:           "var(--bg)",
        surface:      "var(--surface)",
        "surface-2":  "var(--surface-2)",
        "surface-3":  "var(--surface-3)",
        line:         "var(--line)",
        "line-2":     "var(--line-2)",
        text:         "var(--text)",
        "text-2":     "var(--text-2)",
        "text-3":     "var(--text-3)",
        mute:         "var(--mute)",
        accent:       "var(--accent)",
        "accent-2":   "var(--accent-2)",
        "accent-ink": "var(--accent-ink)",
        warn:         "var(--warn)",
        "warn-2":     "var(--warn-2)",
        crit:         "var(--crit)",
        info:         "var(--info)",
        /* ── shadcn compat — ui-accent = hover surface (≠ brand indigo) ── */
        "ui-accent":  "var(--surface-2)",
        /* ── shadcn semantic aliases ────────────────────────────────────── */
        background:   "var(--background)",
        foreground:   "var(--foreground)",
        card: {
          DEFAULT:    "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT:    "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        primary: {
          DEFAULT:    "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT:    "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT:    "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        destructive: {
          DEFAULT:    "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        border:       "var(--border)",
        input:        "var(--input)",
        ring:         "var(--ring)",
      },
      fontFamily: {
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono:    ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        "brand-sm": "var(--r-sm)",
        "brand-md": "var(--r-md)",
        "brand-lg": "var(--r-lg)",
        "brand-xl": "var(--r-xl)",
        /* Keep shadcn keys working */
        lg:         "var(--radius)",
        md:         "calc(var(--radius) - 2px)",
        sm:         "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
