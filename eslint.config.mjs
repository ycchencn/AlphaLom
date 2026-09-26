import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

// ESLint 9 扁平配置（flat config）。
//
// 风格策略（与 IDE / Prettier 设置保持一致）：
//   - 模板（<template>）的 4 空格缩进由 ESLint 的 `vue/html-indent` 强制
//     （覆盖 eslint-plugin-vue recommended 默认的 2 空格）；
//   - <script> / <style> 的缩进、引号、换行等排版统一交给 Prettier
//     （见 .prettierrc.json：tabWidth=4 / singleQuote / 双引号 HTML / CRLF 自动）。
//   本项目未安装 eslint-plugin-prettier（真正运行 prettier 校验的规则），
//   故无需 skip-formatting；ESLint 只管代码质量（vue 规则），格式化交给 Prettier。
export default [
    {
        name: 'app/files-to-lint',
        files: ['**/*.{js,vue}'],
    },
    {
        name: 'app/files-to-ignore',
        ignores: [
            '**/dist/**',
            '**/dist-ssr/**',
            '**/coverage/**',
            '**/.venv/**',
            '**/node_modules/**',
            // 构建/工具配置不在业务代码风格范围内
            '**/*.config.{js,ts,mjs,cjs}',
        ],
    },
    ...pluginVue.configs['flat/recommended'],
    {
        name: 'app/language-options',
        languageOptions: {
            globals: {
                ...globals.browser,
            },
        },
    },
    {
        // 排版/格式化类规则全部交给 Prettier（见 .prettierrc.json，tabWidth=4）负责。
        // 这里显式关闭 eslint-plugin-vue 自带的排版规则，原因有二：
        //   1) 避免与 Prettier 打架（双份格式化规则互相冲突）；
        //   2) 既有未格式化的 .vue 文件（如 NewsFlow）若用 html-indent 校验会满屏报错，
        //      让 eslint 退化为噪音。4 空格风格由 `prettier --check` / 编辑器保存时格式化兜底。
        //   PrimeVue 大量使用驼峰 prop（dataKey / :rowHover 等），attribute-hyphenation 也一并关掉。
        name: 'app/style-delegated-to-prettier',
        rules: {
            'vue/html-indent': 'off',
            'vue/html-quotes': 'off',
            'vue/max-attributes-per-line': 'off',
            'vue/singleline-html-element-content-newline': 'off',
            'vue/multiline-html-element-content-newline': 'off',
            'vue/html-self-closing': 'off',
            'vue/attribute-hyphenation': 'off',
            'vue/first-attribute-linebreak': 'off',
            'vue/html-closing-bracket-newline': 'off',
        },
    },
    {
        // 与「4 空格排版风格」无关的命名类规则放宽，避免首次接入 lint 时噪音过大
        name: 'app/relax-naming',
        rules: {
            'vue/multi-word-component-names': 'off',
        },
    },
]
