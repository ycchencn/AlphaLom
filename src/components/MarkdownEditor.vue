<template>
    <div ref="editorContainerRef" class="monaco-editor-container"></div>
</template>

<script setup>
import {ref, onMounted, onBeforeUnmount, watch} from 'vue';
// 导入 loader 对象
import loader from '@monaco-editor/loader';

// 配置 loader 使用本地路径
// 注意：路径是相对于你的最终 HTML 文件（通常是 index.html）在浏览器中的位置
loader.config({paths: {vs: 'vs'}});

// --- Props ---
const props = defineProps({
    modelValue: {
        type: String,
        default: ''
    },
    language: {
        type: String,
        default: 'markdown'
    },
    theme: {
        type: String,
        default: 'vs-dark'
    },
    options: {
        type: Object,
        default: () => ({})
    }
});

// --- Emits ---
const emit = defineEmits(['update:modelValue', 'change', 'editorDidMount']);

// --- Refs & State ---
const editorContainerRef = ref(null);
let editor = null;
let isEditorReady = false;
let monacoInstance = null; // 缓存 monaco 实例

// --- Methods ---
const loadMonacoAndCreateEditor = async () => {
    if (!editorContainerRef.value) return;

    try {
        // 检查是否已经加载过
        if (!monacoInstance) {
            // 尝试调用 loader 对象上的 init 方法
            monacoInstance = await loader.init();
        }

        // 配置编辑器选项
        const finalOptions = {
            value: props.modelValue,
            language: props.language,
            theme: props.theme,
            automaticLayout: true,
            ...props.options,
        };

        // 创建编辑器实例
        editor = monacoInstance.editor.create(editorContainerRef.value, finalOptions);

        // 监听编辑器内容变化
        const changeSubscription = editor.onDidChangeModelContent(() => {
            if (isEditorReady) {
                const value = editor.getValue();
                emit('update:modelValue', value);
                emit('change', value);
            }
        });

        // 标记编辑器已就绪
        isEditorReady = true;

        // 触发挂载完成事件
        emit('editorDidMount', editor);

    } catch (error) {
        console.error('Failed to initialize Monaco Editor:', error);
    }
};

const disposeEditor = () => {
    if (editor) {
        editor.dispose();
        editor = null;
        isEditorReady = false;
    }
};

// --- Watchers ---
watch(
    () => props.modelValue,
    (newValue) => {
        if (editor && isEditorReady && newValue !== editor.getValue()) {
            editor.setValue(newValue);
        }
    },
    {immediate: false}
);

watch(
    () => props.language,
    (newLanguage) => {
        if (editor && monacoInstance) {
            const model = editor.getModel();
            if (model) {
                monacoInstance.editor.setModelLanguage(model, newLanguage);
            }
        }
    }
);

watch(
    () => props.theme,
    (newTheme) => {
        if (editor && monacoInstance) {
            monacoInstance.editor.setTheme(newTheme);
        }
    }
);

watch(
    () => props.options,
    (newOptions) => {
        if (editor) {
            editor.updateOptions({...newOptions});
        }
    },
    {deep: true}
);

// --- Lifecycle Hooks ---
onMounted(() => {
    loadMonacoAndCreateEditor();
});

onBeforeUnmount(() => {
    disposeEditor();
});
</script>

<style scoped>
.monaco-editor-container {
    width: 100%;
    height: 550px;
    border: 1px solid #ccc;
}
</style>
