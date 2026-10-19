<template>
    <div class="progress-bar" :style="{ width: '100px', height: barHeight + 'px' }">
        <div class="progress-bar-fill" :class="value > 0 ? 'is-up' : 'is-down'" :style="fillStyle"></div>
        <span class="progress-bar-value">{{ value }} %</span>
    </div>
</template>

<script>
export default {
    props: {
        value: {
            type: Number,
            required: true,
            validator: (value) => value >= -100 && value <= 100
        },
        barHeight: {
            type: Number,
            default: 25
        },
        times: {
            type: Number,
            default: 1
        }
    },
    computed: {
        fillStyle() {
            // ⚠️ 只管几何（宽度/位置），颜色交给 CSS 的 .is-up/.is-down：
            //   内联 style 里写死 rgba(255,71,87) 这类色值时暗色模式下永远是亮色，
            //   而 var(--app-up) 只有写在样式表里才能随 .app-dark 切换。
            const absValue = Math.abs(this.value) * this.times;
            if (this.value > 0) {
                return {
                    width: `${absValue / 2}%`,
                    height: '100%',
                    left: '50%',
                    right: 'auto'
                };
            } else if (this.value < 0) {
                return {
                    width: `${absValue / 2}%`,
                    height: '100%',
                    left: `calc(50% - ${absValue / 2}%)`,
                    right: 'auto'
                };
            } else {
                return {
                    width: '0%',
                    height: '100%',
                    left: '50%',
                    right: 'auto'
                };
            }
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
    transition: width 0.3s ease, left 0.3s ease;
    border-radius: 3px;
    opacity: 0.85;
}

/* 涨跌色一律走语义变量，跟随 .app-dark 自动切换，
   也保证和 echartsTheme.js 的 COLORS.up/down 是同一套红绿。 */
.progress-bar-fill.is-up {
    background: linear-gradient(to left, var(--app-up-soft), var(--app-up));
}

.progress-bar-fill.is-down {
    background: linear-gradient(to right, var(--app-down-soft), var(--app-down));
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
