<template>
    <div class="progress-bar" :style="{ width: '100%', height: barHeight + 'px' }">
        <div class="progress-bar-fill"
             :class="value > 40 ? 'is-hot' : 'is-cold'"
             :style="{ width: value + '%', height: '100%' }"></div>
        <span class="progress-bar-value">{{ value }} ℃</span>
    </div>
</template>

<script>
export default {
    props: {
        value: {
            type: Number,
            required: true,
            validator: (value) => value >= 0 && value <= 100
        },
        barHeight: {
            type: Number,
            default: 25
        }
    }
};
</script>

<style scoped>
.progress-bar {
    position: relative;
    background-color: var(--app-bg-active);
    overflow: hidden;
}

.progress-bar-fill {
    position: absolute;
    top: 0;
    left: 0;
    transition: width 0.3s ease;
    border-radius: 3px;
    opacity: 0.85;
}

/* 冷热色同样走语义变量，暗色下自动换档，且与全站红绿保持一致 */
.progress-bar-fill.is-hot {
    background: linear-gradient(to left, var(--app-up-soft), var(--app-up));
}

.progress-bar-fill.is-cold {
    background: linear-gradient(to left, var(--app-down-soft), var(--app-down));
}

.progress-bar-value {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: var(--app-text-primary);
    font-weight: normal;
    z-index: 1; /* 确保文字在进度条之上 */
    font-size: 12px;
    cursor: default;
}
</style>
