/** Build Steward — Tailwind config (standalone CLI, no Node build step). */
module.exports = {
  darkMode: "class",
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        paper: "rgb(var(--c-paper) / <alpha-value>)",
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        "surface-2": "rgb(var(--c-surface-2) / <alpha-value>)",
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        "ink-soft": "rgb(var(--c-ink-soft) / <alpha-value>)",
        line: "rgb(var(--c-border) / <alpha-value>)",
        primary: "rgb(var(--c-primary) / <alpha-value>)",
        "primary-strong": "rgb(var(--c-primary-strong) / <alpha-value>)",
        "primary-soft": "rgb(var(--c-primary-soft) / <alpha-value>)",
        gold: "rgb(var(--c-gold) / <alpha-value>)",
        "gold-soft": "rgb(var(--c-gold-soft) / <alpha-value>)",
        danger: "rgb(var(--c-danger) / <alpha-value>)",
        "danger-soft": "rgb(var(--c-danger-soft) / <alpha-value>)",
        warn: "rgb(var(--c-warn) / <alpha-value>)",
        "warn-soft": "rgb(var(--c-warn-soft) / <alpha-value>)",
      },
      fontFamily: {
        display: ['Georgia', '"Iowan Old Style"', 'Cambria', 'serif'],
        body: ['system-ui', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
      },
      borderRadius: {
        xl: "0.9rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        card: "0 1px 2px rgb(0 0 0 / 0.04), 0 8px 24px -12px rgb(0 0 0 / 0.12)",
        pop: "0 12px 40px -12px rgb(0 0 0 / 0.28)",
      },
      maxWidth: {
        container: "72rem",
      },
    },
  },
  plugins: [],
};
