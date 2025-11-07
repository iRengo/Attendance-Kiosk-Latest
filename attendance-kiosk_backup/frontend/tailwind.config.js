/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}", // include all JS/TS and React files
  ],
  theme: {
    extend: {
      colors: {
        'custom-green': '#22c55e', // Tailwind green-500 hex
        'custom-red': '#ef4444',
        'custom-yellow': '#facc15',
      },
      animation: {
        float: 'float 3s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
    },
  },
  plugins: [],
};
