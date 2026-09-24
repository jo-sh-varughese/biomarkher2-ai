/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  corePlugins: {
    // Preflight is a GLOBAL reset. This project is a Tailwind landing page
    // bolted onto a portal with its own hand-written stylesheet, and letting
    // preflight run would silently restyle every screen of that portal. The
    // few resets the landing actually needs are scoped to `.halo` in
    // src/styles/halo.css instead.
    preflight: false,
  },
  theme: {
    extend: {
      fontFamily: {
        halo: ["'TT Norms Pro'", "'Inter'", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontWeight: {
        // The design tops out at semibold; `font-medium` is the heaviest
        // weight used anywhere, so it maps to 600 rather than Tailwind's 500.
        medium: "600",
      },
      maxWidth: { "88": "88rem" },
    },
  },
  plugins: [],
};
