<script setup>
// ETF 近 N 日走势火花线（轻量内联 SVG，不依赖图表库）。
// 数据来自 GET /api/v1/etf_history/{symbol}（后端已带 1h 缓存），按行 symbol 懒加载。
import {computed, onMounted, ref} from 'vue';
import axios from 'axios';

const props = defineProps({
    symbol: {type: String, required: true},
    days: {type: Number, default: 60},
    width: {type: Number, default: 120},
    height: {type: Number, default: 30},
});

const points = ref([]);
const loading = ref(true);

// 与 ETFDetail.vue 的 fmtDate 保持同一口径：YYYYMMDD（databull SDK 入参格式）
function fmtDate(n) {
    const d = new Date(Date.now() - n * 86400000);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}${m}${day}`;
}

async function load() {
    loading.value = true;
    try {
        const r = await axios.get(`/api/v1/etf_history/${encodeURIComponent(props.symbol)}`, {
            params: {start_date: fmtDate(props.days), end_date: fmtDate(0)},
        });
        points.value = Array.isArray(r.data) ? r.data : [];
    } catch (e) {
        points.value = [];
    } finally {
        loading.value = false;
    }
}

onMounted(load);

const series = computed(() =>
    points.value
        .map(p => Number(p.close))
        .filter(v => !Number.isNaN(v) && v > 0)
);

// 升 = 红（涨），降 = 绿（跌），符合 A 股配色习惯
const up = computed(() => {
    const s = series.value;
    if (s.length < 1) return true;
    return s[s.length - 1] >= s[0];
});
const color = computed(() => (up.value ? '#e23c39' : '#1a9d4b'));

const path = computed(() => {
    const s = series.value;
    if (s.length < 2) return '';
    const min = Math.min(...s);
    const max = Math.max(...s);
    const range = max - min || 1;
    const w = props.width;
    const h = props.height;
    const pad = 2;
    const stepX = (w - pad * 2) / (s.length - 1);
    return s
        .map((v, i) => {
            const x = pad + i * stepX;
            const y = pad + (h - pad * 2) * (1 - (v - min) / range);
            return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
});

const areaPath = computed(() => {
    if (!path.value) return '';
    const w = props.width;
    const h = props.height;
    const pad = 2;
    return `${path.value} L${(w - pad).toFixed(1)},${(h - pad).toFixed(1)} L${pad.toFixed(1)},${(h - pad).toFixed(1)} Z`;
});

const summary = computed(() => {
    const s = series.value;
    if (s.length < 2) return null;
    const first = s[0];
    const last = s[s.length - 1];
    const pct = first ? ((last - first) / first) * 100 : 0;
    return {first, last, pct};
});

// 每个实例梯度 id 唯一，避免多行火花线互相串色
const gid = `spk${Math.random().toString(36).slice(2, 9)}`;
</script>

<template>
    <div class="etf-spark">
        <svg
            v-if="series.length >= 2"
            class="etf-spark__svg"
            :viewBox="`0 0 ${width} ${height}`"
            :width="width"
            :height="height"
            preserveAspectRatio="none"
            :title="summary ? `${symbol} 近${days}日: ${summary.first.toFixed(3)} → ${summary.last.toFixed(3)} (${summary.pct > 0 ? '+' : ''}${summary.pct.toFixed(1)}%)` : symbol"
        >
            <defs>
                <linearGradient :id="gid" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" :stop-color="color" stop-opacity="0.22"/>
                    <stop offset="100%" :stop-color="color" stop-opacity="0"/>
                </linearGradient>
            </defs>
            <path :d="areaPath" :fill="`url(#${gid})`" stroke="none"/>
            <path
                :d="path"
                fill="none"
                :stroke="color"
                stroke-width="1.5"
                stroke-linejoin="round"
                stroke-linecap="round"
            />
        </svg>
        <span v-else-if="loading" class="etf-spark__state">…</span>
        <span v-else class="etf-spark__state">—</span>

        <div v-if="summary" class="etf-spark__pct" :style="{color}">
            {{ summary.pct > 0 ? '+' : '' }}{{ summary.pct.toFixed(1) }}%
        </div>
    </div>
</template>

<style scoped lang="scss">
.etf-spark {
    display: flex;
    flex-direction: column;
    gap: 2px;

    &__svg {
        display: block;
    }

    &__state {
        font-size: 11px;
        color: #9ca3af;
        line-height: 30px;
    }

    &__pct {
        font-size: 10px;
        font-weight: 600;
        line-height: 1;
    }
}
</style>
