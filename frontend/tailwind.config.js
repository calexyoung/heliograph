/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#fef3e2',
          100: '#fde4b9',
          200: '#fcd48c',
          300: '#fbc35f',
          400: '#fab63d',
          500: '#f9a825',
          600: '#f59621',
          700: '#ef811b',
          800: '#e96c16',
          900: '#df4b0d',
        },
        helio: {
          sun: '#f9a825',
          corona: '#ff7043',
          space: '#1a1a2e',
          star: '#e8eaf6',
        }
      },
    },
  },
  plugins: [],
};
