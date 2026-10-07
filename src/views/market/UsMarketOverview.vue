<script setup>
/**
 * 美股大盘监控
 *
 * 数据源：GET /api/v1/index/us_cards（service/us_index_service.py → 上游
 * `databull.get_us_index_history`）。
 *
 * ⚠️ **没有实时行情**：上游美股指数只提供日线（`get_realtime(market='us')`
 * 实测 404），所以所有卡片是**最近一个交易日的收盘**，不是盘中价。
 * 页面文案里不要出现「实时」「盘中」这类词。
 *
 * ⚠️ **各指数最新交易日可能不同**（实测 VIX 比 GSPC 多一天），后端用非波动率
 * 指数的众数当「主日期」，每张卡按自己的 trade_date 显示，别在前端统一化。
 *
 * ⚠️ VIX 是波动率指数、不是价格指数：涨=市场恐慌。它和价格指数并排放在
 * 同一行卡片里时若沿用「红=涨」，VIX 上涨（恐慌）会显示成红色、看着像利好，
 * 所以卡片对 volatility 类反转了着色方向（逻辑在 `@/components/IndexCard.vue`）。
 *
 * 卡片**一行平铺、不分组**，且**与沪深大盘页共用同一个组件**
 * （`@/components/IndexCard.vue`）—— 两页的卡片视觉与算法都只有一处来源，
 * 改一处两页同时生效。本文件只负责取数与页面级布局。
 */
import {ref, computed, onMounted, onUnmounted} from 'vue'
import ToggleSwitch from 'primevue/toggleswitch'
import axios from 'axios'
import {useToast} from 'primevue/usetoast'
import IndexCard from '@/components/IndexCard.vue'

// 日线数据，收盘后不变 → 刷新间隔给长（与大盘页的恐惧贪婪一致）。
const REFRESH_MS = 10 * 60 * 1000

const toast = useToast()

const loading = ref(false)
const error_msg = ref('')
const cards = ref([])
const meta = ref(null)
const auto_refresh = ref(true)
let timer = null

// 顶部的滞后提示：只在真的有指数落后于主日期时说，别天天刷「VIX 领先一天」。
const stale_hint = computed(() => {
    const codes = meta.value?.stale_codes || []
    if (!codes.length) return ''
    return `以下指数数据落后于 ${meta.value.data_date}：${codes.join('、')}`
})

const failed_hint = computed(() => {
    const failed = meta.value?.failed || []
    if (!failed.length) return ''
    return `${failed.length} 个指数取数失败：${failed.map((f) => f.code).join('、')}`
})

// ========================
// 取数
// ========================
const fetchCards = async (silent = false) => {
    if (!silent) loading.value = true
    try {
        const res = await axios.get('/api/v1/index/us_cards')
        const data = res.data
        cards.value = data?.items || []
        meta.value = data?.meta || null
        error_msg.value = ''
    } catch (e) {
        cards.value = []
        meta.value = null
        // 静默刷新失败不清空已有数据（否则定时刷新一次失败页面就白了）
        if (silent) {
            console.warn('美股指数刷新失败', e)
        } else {
            error_msg.value = e?.response?.data?.detail || '美股指数数据获取失败'
            toast.add({severity: 'error', summary: '加载失败', detail: error_msg.value, life: 4000})
        }
    } finally {
        loading.value = false
    }
}

const startTimer = () => {
    stopTimer()
    if (auto_refresh.value) timer = setInterval(() => fetchCards(true), REFRESH_MS)
}

const stopTimer = () => {
    if (timer) {
        clearInterval(timer)
        timer = null
    }
}

const onRefreshToggle = () => {
    if (auto_refresh.value) {
        fetchCards(true)
        startTimer()
    } else {
        stopTimer()
    }
}

// 手动刷新：后端缓存 30 分钟，用 bust 参数强制回源。
// ⚠️ 必须走**已声明**的参数名 `bust`：cache key 由
// md5(module:qualname:args:kwargs) 生成，只有声明过的 query 参数才进 key；
// 写成 `?_=<ts>`（未声明）会被 FastAPI 直接忽略 → 照样命中旧缓存，
// 点「刷新」看起来毫无反应。
const manualRefresh = async () => {
    await axios.get('/api/v1/index/us_cards', {params: {bust: Date.now()}}).then((res) => {
        cards.value = res.data?.items || []
        meta.value = res.data?.meta || null
    }).catch((e) => {
        toast.add({severity: 'error', summary: '刷新失败', detail: '上游接口暂时不可用', life: 4000})
    })
}

onMounted(async () => {
    await fetchCards()
    startTimer()
})

onUnmounted(stopTimer)
</script>

<template>
    <div class="dashboard-container">
        <!-- 顶部标题栏 -->
        <div class="header">
            <div class="title-block">
                <h1 class="title">美股大盘监控</h1>
                <div class="subtitle">
                    数据时间 {{ meta?.data_date || '--' }}（{{ meta?.trade_timezone || 'America/New_York' }} 收盘）
                </div>
            </div>
            <div class="header-right">
                <label class="auto-refresh">
                    <ToggleSwitch v-model="auto_refresh" @change="onRefreshToggle" />
                    <span>{{ auto_refresh ? '自动刷新 10min' : '已暂停' }}</span>
                </label>
                <button class="refresh-btn" :disabled="loading" @click="manualRefresh">
                    <i class="pi pi-refresh" :class="{spin: loading}"></i>
                    <span>刷新</span>
                </button>
            </div>
        </div>

        <!-- 异常提示：仅在有值时出现（取数失败 / 指数数据滞后）。
             原先这里还有一条常驻「口径说明」提示条，按用户要求去掉了 ——
             它每次都在、看一次就够，属于噪音；而这两个提示只在**真的出问题**时
             才出现，是会「说话」的，不能跟着一起删。 -->
        <div v-if="error_msg || stale_hint || failed_hint" class="error-box">
            <div v-if="error_msg">{{ error_msg }}</div>
            <div v-if="stale_hint">{{ stale_hint }}</div>
            <div v-if="failed_hint">{{ failed_hint }}</div>
        </div>

        <!-- 指数卡片：一行平铺，不分组（与沪深大盘页一致，共用 IndexCard 组件） -->
        <div class="indices-row">
            <IndexCard
                v-for="item in cards"
                :key="item.code"
                :item="item"
                :tag-text="item.is_volatility ? '恐慌指数' : ''"
            />
        </div>

        <div v-if="!loading && !cards.length" class="empty-tip">暂无美股指数数据</div>
    </div>
</template>

<style scoped lang="scss">
.dashboard-container {
    /* 页面外边距对齐全站约定：横向 2rem（=24px），与 .card 内容左边缘一致（204）。
       与 MarketOverview.vue 保持相同。 */
    padding: 2rem;
    background: #f5f7fb;
    min-height: 100vh;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    gap: 0.75rem;

    .title-block {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .title {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1e293b;
        margin: 0;
    }

    .subtitle {
        font-size: 0.85rem;
        color: #64748b;
    }

    .header-right {
        display: flex;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
    }
}

.auto-refresh {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    color: #475569;
    font-size: 0.9rem;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}

.refresh-btn {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.45rem 0.8rem;
    font-size: 0.85rem;
    color: #475569;
    background: #fff;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    cursor: pointer;
    white-space: nowrap;

    &:hover:not(:disabled) {
        border-color: var(--primary-color);
        color: var(--primary-color);
    }

    &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .spin {
        animation: us-spin 1s linear infinite;
    }
}

@keyframes us-spin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}

/* 异常提示条（取数失败 / 数据滞后）。原先还有一个常驻的蓝色「口径说明」提示条，
   按用户要求去掉了（每次都在、看一次就够），样式一并清掉。 */
.error-box {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.75rem 1rem;
    margin-bottom: 1.25rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 8px;
    color: #b91c1c;
    font-size: 0.9rem;
}

/* 指数卡片行：flex-wrap + flex:1 1（与沪深大盘页 `.indices-row` 同一套）。
   ⚠️ 别用 grid：11 张卡除以 4 列是 4+4+3，grid 下最后一行会缺一格、右侧留空。
   flex 让每行的卡片自动拉伸填满整行，最后一行 3 张照样铺满。 */
.indices-row {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1.5rem;
}

/* 卡片自身样式在 IndexCard.vue 里（两页共用）。这里只管行布局：
   flex-wrap + flex:1 1 让每行卡片自动拉伸铺满 —— 11 张卡 4+4+3，最后一行不空一格。
   ⚠️ 别用 grid：11/4 除不尽，最后一行会缺格。 */
.index-card {
    flex: 1 1 calc(25% - 0.75rem);
    min-width: 240px;
}

.empty-tip {
    padding: 2rem;
    text-align: center;
    color: #94a3b8;
}
</style>
