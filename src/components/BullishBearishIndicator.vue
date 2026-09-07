<!-- BullishBearishBar.vue -->
<template>
    <div v-if="value !== 0" class="bullish-bearish-bar">
        <Tag :severity="severity" size="small">{{ label }}</Tag>
        <div class="strength-bar">
            <div
                v-for="i in maxSegments"
                :key="i"
                class="bar-segment"
                :class="{
          filled: i <= filledSegments,
          bullish: value > 0,
          bearish: value < 0
        }"
            ></div>
        </div>
    </div>
</template>

<script setup>
import {computed} from 'vue'

const props = defineProps({
    value: {
        type: Number,
        required: true,
        validator: (val) => val >= -10 && val <= 10
    },
    maxSegments: {
        type: Number,
        default: 5,
        validator: (val) => Number.isInteger(val) && val > 0 && val <= 20 // 限制合理范围
    }
})

const label = computed(() => (props.value > 0 ? '利多' : '利空'))

const severity = computed(() => (props.value < 0 ? 'success' : 'danger'))

// 将 [-10,10] 映射到 [0, maxSegments]
const filledSegments = computed(() => {
    const absValue = Math.abs(props.value)
    // 线性映射：absValue / 10 * maxSegments
    const raw = (absValue / 10) * props.maxSegments
    return Math.floor(raw) // 只填充完整格子（可改为 Math.round 或保留小数做半格）
})

</script>

<style scoped>
.bullish-bearish-bar {
    display: flex;
    align-items: center;
    gap: 0.6rem;
}

.strength-bar {
    display: flex;
    gap: 2px;
    height: 16px;
}

.bar-segment {
    width: 14px;
    height: 100%;
    border-radius: 2px;
    background-color: #e0e0e0;
}

.bar-segment.filled.bullish {
    background-color: #f44336;
}

.bar-segment.filled.bearish {
    background-color: #4caf50;
}

</style>
