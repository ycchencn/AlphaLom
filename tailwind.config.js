/** @type {import('tailwindcss').Config} */
module.exports = {
    // ⚠️ 用精确类名匹配，不要写成 '[class*="app-dark"]'：
    // 子串匹配会让任何恰好含这串字符的类名（如 xxx-app-dark-extra）也命中。
    // 类名需与 main.js 的 DARK_SELECTOR、_dark.scss 的选择器保持一致。
    darkMode: ['selector', '.app-dark'],
    content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
    plugins: [require('tailwindcss-primeui')],
    theme: {
        screens: {
            sm: '576px',
            md: '768px',
            lg: '992px',
            xl: '1200px',
            '2xl': '1920px'
        }
    }
};
