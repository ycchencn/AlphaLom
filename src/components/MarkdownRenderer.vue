<template>
    <!-- 通过 inline style 注入 CSS 变量，兼容所有 Vue 3 版本 -->
    <article :class="$style.markdownWrapper" :style="{ '--md-font-size': fontSize }">
        <div :class="$style.markdownContent" v-html="compiledMarkdown"></div>
    </article>
</template>

<script>
import {ref, watch} from 'vue';
import {marked} from 'marked';
import markedKatex from 'marked-katex-extension';

// 配置 marked
marked.use(markedKatex({
    throwOnError: false,
    inlineDelimiters: [['$', '$'], ['\\(', '\\)']],
    blockDelimiters: [['$$', '$$'], ['\\[', '\\]']]
}));

export default {
    name: 'MarkdownRenderer',
    props: {
        markdown: {
            type: String,
            required: true
        },
        // 🆕 新增：基础字体大小控制
        fontSize: {
            type: String,
            default: '12px'
        }
    },
    setup(props) {
        const compiledMarkdown = ref('');

        const renderMarkdown = (text) => {
            if (!text) {
                compiledMarkdown.value = '';
                return;
            }
            try {
                compiledMarkdown.value = marked.parse(text);
            } catch (e) {
                console.error('Markdown/KaTeX parsing error:', e);
                compiledMarkdown.value = `<p style="color:red">解析失败: ${e.message}</p>`;
            }
        };

        watch(() => props.markdown, (newVal) => {
            renderMarkdown(newVal);
        }, {immediate: true});

        return {compiledMarkdown};
    }
};
</script>

<style module>
/* 变量作用域容器，设置默认回退值 */
.markdownWrapper {
    --md-font-size: var(--md-font-size, 12px);
}

.markdownContent {
    font-size: var(--md-font-size);
    line-height: 1.5;
    /* 正文色走语义变量，暗色下自动反色。
       KaTeX 公式自身不写颜色（走 currentColor 继承），这里改了公式跟着变。 */
    color: var(--app-text-primary);
    max-width: none;
    margin: 0;
    padding: 5px;
    text-align: left;
}

/* 标题：改为相对单位，层级差异更自然 */
.markdownContent h1 {
    font-size: 1.75em;
    margin-top: 1.2em;
    margin-bottom: 0.6em;
}

.markdownContent h2 {
    font-size: 1.5em;
    margin-top: 1em;
    margin-bottom: 0.5em;
}

.markdownContent h3 {
    font-size: 1.3em;
    margin-top: 0.9em;
    margin-bottom: 0.4em;
}

.markdownContent h4 {
    font-size: 1.2em;
    margin-top: 0.8em;
    margin-bottom: 0.3em;
}

.markdownContent h5, .markdownContent h6 {
    font-size: 1.1em;
    margin-top: 0.7em;
    margin-bottom: 0.3em;
}

.markdownContent h1, .markdownContent h2, .markdownContent h3,
.markdownContent h4, .markdownContent h5, .markdownContent h6 {
    font-weight: 600;
    color: var(--app-text-primary);
    line-height: 1.3;
    border-bottom: none;
    padding: 0;
}

.markdownContent p {
    margin: 0 0 0.8em 0;
}

.markdownContent a {
    color: var(--app-link);
    text-decoration: none;
}

.markdownContent a:hover {
    text-decoration: underline;
}

/* 行内代码 */
.markdownContent code {
    background-color: var(--app-bg-subtle);
    padding: 0.2em 0.4em;
    border-radius: 3px;
    font-size: 0.9em;
    /* 行内代码是标识符不是涨跌信号，用强调色而非 --app-up/--app-down */
    color: var(--app-text-primary);
}

/* 代码块 */
.markdownContent pre {
    background-color: var(--app-bg-subtle);
    border: 1px solid var(--app-border-weak);
    border-radius: 4px;
    padding: 0.8em;
    overflow-x: auto;
    margin: 0.8em 0;
    font-size: 0.9em;
    line-height: 1.4;
}

.markdownContent pre code {
    background: none;
    padding: 0;
    color: var(--app-text-primary);
    font-size: inherit;
}

/* 引用 */
.markdownContent blockquote {
    margin: 0.8em 0;
    padding-left: 0.75em;
    border-left: 3px solid var(--app-link);
    background-color: var(--app-bg-subtle);
    color: var(--app-text-secondary);
    font-style: normal;
    font-size: inherit;
}

.markdownContent blockquote p {
    margin: 0;
}

/* 列表 */
.markdownContent ul, .markdownContent ol {
    padding-left: 1.5em;
    margin: 0 0 0.8em 0;
    font-size: inherit;
}

.markdownContent li {
    margin-bottom: 0.3em;
    list-style: circle;
}

/* 表格 */
.markdownContent table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.8em 0;
    font-size: inherit;
}

.markdownContent th, .markdownContent td {
    padding: 0.45em 0.6em;
    text-align: left;
    border: 1px solid var(--app-border-weak);
}

.markdownContent th {
    background-color: var(--app-bg-active);
    font-weight: 600;
}

/* 斑马纹用极淡的一档，暗色下再淡就等于没有条纹 */
.markdownContent tr:nth-child(even) {
    background-color: var(--app-line-soft);
}

/* 公式 */
.markdownContent .katex {
    font-size: 1.1em;
    vertical-align: middle;
}

.markdownContent .katex-display {
    margin: 1.2em 0;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.5em 0;
}

.markdownContent .katex-display > .katex {
    max-width: 100%;
    overflow-x: auto;
    display: block;
}
</style>