/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'hifi-dark': '#0a0a0a',
        'hifi-panel': '#0f0f0f',
        'hifi-gray': '#1a1a1a',
        'hifi-surface': '#161616',
        'hifi-light': '#2a2a2a',
        'hifi-accent': '#3a3a3a',
        'hifi-border': '#252525',
        'hifi-gold': '#d4af37',
        'hifi-silver': '#c0c0c0',
      },
      fontFamily: {
        'display': ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        'hifi': '0 4px 20px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1)',
        'hifi-inset': 'inset 0 2px 8px rgba(0, 0, 0, 0.4)',
      },
    },
  },
  plugins: [],
}

