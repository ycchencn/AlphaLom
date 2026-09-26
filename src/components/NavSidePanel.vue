<script setup>
// 通用左侧导航面板：股票池分组、新闻话题列表等共用，保证视觉与交互完全一致。
// 视觉 1:1 照抄 /market/news_flow 话题列表（白底 + 灰底表头 + rounded-md 项 +
// hover:bg-blue-50 + 选中项 bg-blue-50/text-blue-700/左侧蓝条）。
// 关键点：列表项使用 body 默认字号 12px（根字号 12px），与 news_flow 话题项一致；
//         之前误用 text-sm(10.5px) 导致"小一号"，现已对齐。
const props = defineProps({
    title: { type: String, default: '分组' },
    subtitle: { type: String, default: '' },
    // [{ key, label, count?, actions?: [{type, iconClass, title}] }]
    items: { type: Array, required: true },
    activeKey: { type: [String, Number], default: '' },
    // 窄屏（≤1100px）时从左侧栏变为顶部横向滚动条
    responsive: { type: Boolean, default: true },
});
const emit = defineEmits(['select', 'action']);

function onSelect(item) {
    emit('select', item.key);
}
function onAction(item, action) {
    emit('action', { key: item.key, type: action.type });
}
</script>

<template>
    <aside class="nav-side-panel" :class="{ 'is-responsive': responsive }">
        <div class="nav-side-header">
            <h3 class="nav-side-title">{{ title }}</h3>
            <p v-if="subtitle" class="nav-side-sub">{{ subtitle }}</p>
        </div>
        <div class="nav-side-items">
            <div
                v-for="item in items"
                :key="item.key"
                class="nav-side-item"
                :class="{ active: item.key === activeKey }"
                @click="onSelect(item)"
            >
                <span class="nav-side-label">{{ item.label }}</span>
                <span v-if="item.count !== undefined && item.count !== null" class="nav-side-count">{{ item.count }}</span>
                <span v-if="item.actions && item.actions.length" class="nav-side-actions">
                    <button
                        v-for="a in item.actions"
                        :key="a.type"
                        type="button"
                        :title="a.title"
                        class="nav-side-action-btn"
                        @click.stop="onAction(item, a)"
                    >
                        <i :class="a.iconClass"></i>
                    </button>
                </span>
            </div>
        </div>
    </aside>
</template>

<style scoped>
/* 面板：照搬 news_flow 左侧栏 min-w-56 border-r bg-white shadow-sm
   min-w-56 = 14rem，根字号 12px → 168px */
.nav-side-panel {
    width: 168px;
    flex: 0 0 168px;
    border-right: 1px solid #e5e7eb;
    background: #fff;
    display: flex;
    flex-direction: column;
    box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    overflow: hidden;
    font-family: 'Lato', sans-serif;
}

/* 表头：p-4 border-b bg-gray-50 */
.nav-side-header {
    padding: 16px;
    border-bottom: 1px solid #e5e7eb;
    background: #f9fafb;
}

/* 标题：font-semibold text-base text-gray-700 → 12px */
.nav-side-title {
    margin: 0;
    font-weight: 600;
    font-size: 12px;
    color: #374151;
}

/* 副标题：text-xs text-gray-400 mt-1 leading-snug → 9px */
.nav-side-sub {
    margin: 4px 0 0;
    font-size: 9px;
    color: #9ca3af;
    line-height: 1.375;
}

/* 列表容器：flex-1 overflow-y-auto p-2 space-y-1 */
.nav-side-items {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

/* 列表项：px-3 py-2.5 rounded-md hover:bg-blue-50，默认字号 12px（与 news_flow 一致） */
.nav-side-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
    color: #374151;
    border-left: 4px solid transparent;
    transition: all 0.2s;
}

.nav-side-item:hover {
    background: #eff6ff; /* blue-50 */
}

/* 选中：bg-blue-50 text-blue-700 font-semibold border-l-4 border-blue-500 */
.nav-side-item.active {
    background: #eff6ff;
    color: #1d4ed8;
    font-weight: 600;
    border-left-color: #3b82f6;
}

.nav-side-label {
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.nav-side-count {
    flex: 0 0 auto;
    font-size: 9px;
    opacity: 0.7;
}

.nav-side-actions {
    display: none;
    flex: 0 0 auto;
    gap: 4px;
}

.nav-side-item:hover .nav-side-actions {
    display: inline-flex;
}

.nav-side-action-btn {
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 0 2px;
    font-size: 10px;
    line-height: 1;
    color: #6b7280;
}

.nav-side-action-btn:hover {
    color: #1d4ed8;
}

/* 窄屏：左侧栏 → 顶部横向滚动条 */
@media (max-width: 1100px) {
    .nav-side-panel.is-responsive {
        width: auto;
        flex: none;
        flex-direction: row;
        align-items: center;
        border-right: none;
        border-bottom: 1px solid #e5e7eb;
        box-shadow: none;
        overflow-x: auto;
        position: sticky;
        top: 0;
        z-index: 5;
    }

    .nav-side-panel.is-responsive .nav-side-header {
        display: none;
    }

    .nav-side-panel.is-responsive .nav-side-items {
        flex-direction: row;
        flex-wrap: nowrap;
        overflow-x: auto;
        padding: 8px;
        gap: 6px;
    }

    .nav-side-panel.is-responsive .nav-side-item {
        flex: 0 0 auto;
        white-space: nowrap;
    }

    .nav-side-panel.is-responsive .nav-side-label {
        flex: 0 0 auto;
        overflow: visible;
        text-overflow: clip;
    }
}
</style>
