<template>
    <!-- 可视化进度条 -->
    <div class="range-visual">
        <div class="range-track">
            <!-- 这里的宽度由 computed 属性计算得出 -->
            <div
                class="range-fill"
                :style="{ width: percentage + '%' }"
            >
                <!-- 指示器圆点 -->
                <div class="range-indicator"></div>
            </div>
        </div>
        <!-- 底部数值标签 -->
        <div class="range-labels">
            <span class="min-price">{{ formatCurrency(low52w) }}</span>
            <span class="max-price">{{ formatCurrency(high52w) }}</span>
        </div>
    </div>
</template>

<script setup>
import {computed} from 'vue';

// 定义 Props
const props = defineProps({
    low52w: {
        type: Number,
        required: true,
        validator: (value) => value >= 0
    },
    high52w: {
        type: Number,
        required: true,
        validator: (value) => value >= 0
    },
    currentPrice: {
        type: Number,
        required: true,
        validator: (value) => value >= 0
    }
});

// 计算当前价格在区间中的百分比位置
const percentage = computed(() => {
    const {low52w, high52w, currentPrice} = props;

    // 防止除以 0 或区间为 0 的情况
    if (high52w === low52w) return 0;

    // 计算百分比
    let percent = ((currentPrice - low52w) / (high52w - low52w)) * 100;

    // 限制在 0% - 100% 之间，防止指示器跑出进度条
    return Math.max(0, Math.min(100, percent));
});

// 数字格式化（带千分位，保留两位小数，无货币符号）
const formatCurrency = (value) => {
    return new Intl.NumberFormat('zh-CN', {
        style: 'decimal',    // 修改这里：从 'currency' 改为 'decimal'
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
};
</script>

<style scoped>

/* 进度条样式 */
.range-visual {
    margin-top: 10px;
}

.range-track {
    height: 5px;
    background-color: #eef0f2;
    border-radius: 4px;
    position: relative;
    overflow: visible; /* 允许指示器超出一点视觉效果 */
}

.range-fill {
    height: 100%;
    border-radius: 4px;
    position: relative;
    transition: width 0.5s ease-out; /* 添加动画效果 */
}

/* 指示器圆点 */
.range-indicator {
    position: absolute;
    right: -6px; /* 居中于线条末端 */
    top: 50%;
    transform: translateY(-50%);
    width: 10px;
    height: 10px;
    background-color: #fff;
    border: 2px solid #3b82f6;
    border-radius: 50%;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.range-labels {
    display: flex;
    justify-content: space-between;
    margin-top: 5px;
    font-size: .685rem;
    color: #888;
}

.min-price {
    font-weight: 500;
}

.max-price {
    font-weight: 500;
}
</style>
