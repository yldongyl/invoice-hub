/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./web/**/*.html', './web/js/**/*.js'],
  safelist: [
    'hidden',
    'block',
    'flex',
    'inline-flex',
    'opacity-0',
    'opacity-60',
    'opacity-70',
    'opacity-100',
    'translate-y-2',
    'pointer-events-none',
    'row-sel',
    {
      pattern: /(bg|text|border|hover:bg|hover:text|hover:border|dark:bg|dark:text|dark:border)-(primary|success|warning|danger|purple)(-light|-mid)?/,
    },
    {
      pattern: /(bg|text|border|hover:bg|hover:text|hover:border|dark:bg|dark:text|dark:border)-(ink|gray)-(1|2|3|4|100|200|300|400|500|600|700|800|900)/,
    },
  ],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#165DFF', light: '#F0F5FF', mid: '#BEDAFF', deep: '#0E42D2' },
        success: { DEFAULT: '#00B42A', light: '#E8FFEA' },
        warning: { DEFAULT: '#FF7D00', light: '#FFF7E8' },
        danger: { DEFAULT: '#F53F3F', light: '#FFECE8' },
        purple: { DEFAULT: '#722ED1', light: '#F5E8FF' },
        ink: { 1: '#1D2129', 2: '#4E5969', 3: '#86909C', 4: '#C9CDD4' },
        line: '#E5E6EB',
        surface: '#F7F8FA',
        card: '#FFFFFF',
        dcard: '#1D2129',
        dline: '#333A45',
      },
      fontFamily: {
        sans: ['Inter', 'Noto Sans SC', 'Source Han Sans SC', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
      },
      boxShadow: {
        card: '0 2px 8px rgba(29,33,41,.06)',
        cardhover: '0 4px 16px rgba(29,33,41,.10)',
        login: '0 8px 40px rgba(29,33,41,.12)',
      },
      borderRadius: {
        card: '8px',
      },
    },
  },
};
