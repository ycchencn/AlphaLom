<script setup>
/**
 * L3 · 因子选股器 + 技术信号扫描
 *
 * 数据来源（routes/factor.py）：
 *   GET  /api/v1/factor/catalog              因子字典（条件构造器的候选项）
 *   POST /api/v1/factor/screen               按因子条件选股（截至 asof 的最新值）
 *   GET  /api/v1/factor/signals/catalog      可用技术信号清单
 *   GET  /api/v1/factor/signals?signal=...   信号扫描（纯规则，零 token）
 *   PUT  /api/v1/stocks/{symbol}             一键加入股票池（monitoring=1）
 *
 * 设计：
 *   - 两个 Tab：选股器（条件构建）/ 信号扫描（预设规则）。
 *   - 选的因子全程只用 factor_name，中文名从 catalog 拿，避免前后端各自维护一份映射。
 *   - 「加入池」复用既有的 PUT /stocks/{symbol}，与股票池页面同一入口，不另起炉灶。
 */
import {computed, onMounted, ref} from 'vue';
import axios from 'axios';
import {useToast} from 'primevue/usetoast';

const toast = useToast();

// ==================== 公共状态 ====================
const activeTab = ref('screen');

const catalog = ref(null);          // {groups, factors}
const catalogMap = ref({});         // field -> factor 元信息（含中文名）
const loadingCatalog = ref(false);

const OP_OPTIONS = [
    {label: '≥ 大于等于', value: '>='},
    {label: '≤ 小于等于', value: '<='},
    {label: '> 大于', value: '>'},
    {label: '< 小于', value: '<'},
    {label: '= 等于', value: '=='},
];

// 常用因子组合预设（省去每次手搭条件）
//
// ⚠️ 阈值单位必须与因子落库口径一致 —— 见 service/factor_cal_service.py 的公式：
//   mom_w   = close/close.shift(w) - 1        → **小数**（0.1 = 10%），不是百分数
//   vol_w   = ret.rolling(w).std()*sqrt(252)  → **小数**（0.3 = 30% 年化波动）
//   bias_w  = (close - ma)/ma                 → **小数**
//   rsi_14                                    → 0~100
//   52week_position                           → 0~100（库里已 ×100）
// 曾按「百分数」写阈值（mom_20 >= 5、vol_20 <= 25），实测全部 0 命中。
const PRESETS = [
    {
        name: '强势突破',
        desc: '20日涨幅 > 3% 且位于 52 周区间上半部',
        conditions: [
            {field: 'mom_20', operator: '>=', value: 0.03},
            {field: '52week_position', operator: '>=', value: 50},
        ],
    },
    {
        name: '超跌反弹候选',
        desc: 'RSI 超卖 + 接近 52 周低位',
        conditions: [
            {field: 'rsi_14', operator: '<=', value: 35},
            {field: '52week_position', operator: '<=', value: 30},
        ],
    },
    {
        name: '低波动稳健',
        desc: '年化波动率 < 30% 且中长期动量为正',
        conditions: [
            {field: 'vol_20', operator: '<=', value: 0.3},
            {field: 'mom_50', operator: '>=', value: 0},
        ],
    },
    {
        name: '量价齐升',
        desc: '5 日均量超 20 日均量 + 20 日动量为正',
        conditions: [
            {field: 'turnover_5', operator: '>=', value: 300000},
            {field: 'mom_20', operator: '>=', value: 0.02},
        ],
    },
];

// ==================== 选股器 ====================
const conditions = ref([]);          // [{field, operator, value}]
const screenLoading = ref(false);
const screenResult = ref(null);
const screenLimit = ref(50);
const addingSymbol = ref(null);

const factorOptions = computed(() => {
    if (!catalog.value?.factors) return [];
    // 按分组排好序，OptGroup 用
    return catalog.value.factors.map((f) => ({
        label: `${f.name}（${f.field}）`,
        value: f.field,
        group: f.group || 'other',
    }));
});

const factorGroups = computed(() => {
    const groups = (catalog.value?.groups || []).map((g) => ({
        key: g.key,
        label: g.label,
        items: factorOptions.value.filter((o) => o.group === g.key),
    }));
    const others = factorOptions.value.filter((o) => o.group === 'other');
    if (others.length) groups.push({key: 'other', label: '形态与其他', items: others});
    return groups.filter((g) => g.items.length);
});

function factorLabel(field) {
    return catalogMap.value[field]?.name || field;
}

// 阈值单位提示：因子口径差异很大（小数 / 0~100 / 绝对价格），
// 不提示的话用户很容易把 「涨 3%」填成 3（实际应为 0.03）导致 0 命中。
const UNIT_HINTS = {
    mom: '小数（0.03 = 3%）',
    bias: '小数（0.03 = 3%）',
    vol: '小数（0.3 = 30% 年化）',
    rsi: '0~100',
    '52week_position': '0~100',
    atr: '价格（元）',
    turnover: '股数（成交量）',
    macd: '绝对差值',
    is_ma_bullish: '1=是, 0=否',
    closing_strength: '0~1',
};

function unitHint(field) {
    if (!field) return '';
    if (UNIT_HINTS[field]) return UNIT_HINTS[field];
    for (const [k, v] of Object.entries(UNIT_HINTS)) {
        if (field.startsWith(k)) return v;
    }
    return '';
}

function addCondition(field = null) {
    conditions.value.push({
        field: field || factorGroups.value[0]?.items[0]?.value || '',
        operator: '>=',
        value: 0,
    });
}

function removeCondition(idx) {
    conditions.value.splice(idx, 1);
}

function applyPreset(p) {
    conditions.value = p.conditions.map((c) => ({...c}));
    screenResult.value = null;
}

async function runScreen() {
    const valid = conditions.value.filter((c) => c.field);
    if (!valid.length) {
        toast.add({severity: 'warn', summary: '请至少添加一个因子条件', life: 2500});
        return;
    }
    const payload = {};
    for (const c of valid) {
        payload[c.field] = {operator: c.operator, value: Number(c.value)};
    }
    screenLoading.value = true;
    try {
        const {data} = await axios.post('/api/v1/factor/screen', {
            conditions: payload,
            limit: Number(screenLimit.value) || 50,
        });
        screenResult.value = data?.data ?? data;
    } catch (e) {
        screenResult.value = null;
        toast.add({
            severity: 'error',
            summary: '选股失败',
            detail: e?.response?.data?.detail || e.message,
            life: 4000,
        });
    } finally {
        screenLoading.value = false;
    }
}

const screenRows = computed(() => screenResult.value?.rows || []);
const screenCols = computed(() => {
    const r = screenRows.value[0];
    if (!r) return [];
    return Object.keys(r).filter((k) => k !== 'symbol' && k !== 'name');
});

// ==================== 信号扫描 ====================
const signalCatalog = ref([]);
const signalKey = ref('');
const signalScope = ref('monitoring');
const signalLoading = ref(false);
const signalResult = ref(null);

const currentSignal = computed(
    () => signalCatalog.value.find((s) => s.key === signalKey.value) || null,
);

async function loadSignalCatalog() {
    try {
        const {data} = await axios.get('/api/v1/factor/signals/catalog');
        const list = data?.data ?? data;
        signalCatalog.value = Array.isArray(list) ? list : [];
        if (!signalKey.value && signalCatalog.value.length) {
            signalKey.value = signalCatalog.value[0].key;
        }
    } catch (e) {
        signalCatalog.value = [];
    }
}

async function runScan() {
    if (!signalKey.value) return;
    signalLoading.value = true;
    try {
        const {data} = await axios.get('/api/v1/factor/signals', {
            params: {signal: signalKey.value, scope: signalScope.value, limit: 200},
        });
        signalResult.value = data?.data ?? data;
    } catch (e) {
        signalResult.value = null;
        toast.add({
            severity: 'error',
            summary: '扫描失败',
            detail: e?.response?.data?.detail || e.message,
            life: 4000,
        });
    } finally {
        signalLoading.value = false;
    }
}

const signalRows = computed(() => signalResult.value?.rows || []);
const signalCols = computed(() => {
    const r = signalRows.value[0];
    if (!r) return [];
    return Object.keys(r).filter((k) => k !== 'symbol' && k !== 'name');
});

// ==================== 加入股票池 ====================
async function addToPool(row) {
    if (!row?.symbol) return;
    addingSymbol.value = row.symbol;
    try {
        await axios.put(`/api/v1/stocks/${row.symbol}`, {monitoring: 1});
        toast.add({
            severity: 'success',
            summary: `${row.symbol} 已加入股票池`,
            life: 2000,
        });
    } catch (e) {
        toast.add({
            severity: 'error',
            summary: '加入失败',
            detail: e?.response?.data?.detail || e.message,
            life: 3500,
        });
    } finally {
        addingSymbol.value = null;
    }
}

// ==================== 初始化 ====================
async function loadCatalog() {
    loadingCatalog.value = true;
    try {
        const {data} = await axios.get('/api/v1/factor/catalog');
        const d = data?.data ?? data;
        catalog.value = d;
        const map = {};
        for (const f of d?.factors || []) map[f.field] = f;
        catalogMap.value = map;
        if (!conditions.value.length) {
            // 默认给一组「动量 + 区间位置」，让用户一进来就能直接跑一次看效果。
            // ⚠️ mom_20 是小数口径（0.03 = 3%），见上方 PRESETS 注释。
            conditions.value = [
                {field: 'mom_20', operator: '>=', value: 0.02},
                {field: '52week_position', operator: '>=', value: 50},
            ];
        }
    } catch (e) {
        catalog.value = null;
    } finally {
        loadingCatalog.value = false;
    }
}

onMounted(async () => {
    await Promise.all([loadCatalog(), loadSignalCatalog()]);
});

function fmtNum(v) {
    if (v == null || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return String(v);
    return Math.abs(n) >= 1000 ? n.toFixed(0) : n.toFixed(2);
}
</script>

<template>
    <div class="fs-wrap">
        <Toast/>

        <!-- 顶部 Tab 切换 -->
        <div class="fs-tabs">
            <button class="fs-tab" :class="{active: activeTab === 'screen'}"
                    @click="activeTab = 'screen'">
                <i class="pi pi-filter"></i> 因子选股器
            </button>
            <button class="fs-tab" :class="{active: activeTab === 'signal'}"
                    @click="activeTab = 'signal'">
                <i class="pi pi-bolt"></i> 技术信号扫描
            </button>
            <span class="fs-tabs-hint">
                数据来自已落库的因子库（factor_values），全部为纯规则计算，不消耗大模型额度。
            </span>
        </div>

        <!-- ==================== Tab 1 · 选股器 ==================== -->
        <div v-if="activeTab === 'screen'" class="fs-pane">
            <div class="fs-panel">
                <div class="fs-panel-h">
                    <span><i class="pi pi-sliders-h text-blue-500"></i> 条件构建</span>
                    <span class="fs-sub" v-if="catalog">
                        可选因子 {{ Object.keys(catalogMap).length }} 个
                    </span>
                </div>

                <!-- 预设 -->
                <div class="fs-presets">
                    <span class="fs-presets-k">快速预设</span>
                    <button v-for="p in PRESETS" :key="p.name" class="fs-preset"
                            :title="p.desc" @click="applyPreset(p)">
                        {{ p.name }}
                    </button>
                </div>

                <!-- 条件列表 -->
                <div class="fs-conds">
                    <div v-for="(c, i) in conditions" :key="i" class="fs-cond">
                        <Select
                            v-model="c.field"
                            :options="factorGroups"
                            optionGroupLabel="label"
                            optionGroupChildren="items"
                            optionLabel="label"
                            optionValue="value"
                            filter
                            class="fs-cond-field"
                            placeholder="选择因子"
                        />
                        <Select
                            v-model="c.operator"
                            :options="OP_OPTIONS"
                            optionLabel="label"
                            optionValue="value"
                            class="fs-cond-op"
                        />
                        <InputText
                            v-model="c.value"
                            type="number"
                            class="fs-cond-val"
                            placeholder="阈值"
                        />
                        <span v-if="unitHint(c.field)" class="fs-cond-unit">
                            {{ unitHint(c.field) }}
                        </span>
                        <Button icon="pi pi-times" text severity="secondary" size="small"
                                @click="removeCondition(i)"/>
                    </div>
                    <div v-if="!conditions.length" class="fs-empty-hint">
                        还没有条件，点「添加条件」或选一个快速预设。
                    </div>
                </div>

                <div class="fs-actions">
                    <Button label="添加条件" icon="pi pi-plus" size="small" outlined
                            @click="addCondition()"/>
                    <div class="fs-actions-right">
                        <span class="fs-limit-k">最多返回</span>
                        <InputText v-model="screenLimit" type="number" class="fs-limit"/>
                        <Button label="开始选股" icon="pi pi-search" size="small"
                                :loading="screenLoading" @click="runScreen"/>
                    </div>
                </div>

                <!-- 条件预览（把选中的因子翻译成中文） -->
                <div v-if="conditions.length" class="fs-preview">
                    逻辑
                    <b class="fs-and">AND</b>：
                    <span v-for="(c, i) in conditions" :key="'p' + i" class="fs-chip">
                        {{ factorLabel(c.field) }}
                        {{ OP_OPTIONS.find(o => o.value === c.operator)?.label.slice(0, 1) }}
                        {{ c.value }}
                    </span>
                </div>
            </div>

            <!-- 结果 -->
            <div class="fs-panel" v-if="screenResult">
                <div class="fs-panel-h">
                    <span><i class="pi pi-table text-blue-500"></i> 选股结果</span>
                    <span class="fs-sub">
                        命中 <b>{{ screenResult.count }}</b> 只 · 截至 {{ screenResult.asof }}
                    </span>
                </div>
                <div v-if="!screenRows.length" class="fs-empty-hint">
                    没有标的满足全部条件，试着放宽阈值或减少条件。
                </div>
                <DataTable v-else :value="screenRows" :rows="25" paginator
                           :rowsPerPageOptions="[25, 50, 100]" size="small"
                           scrollable scrollHeight="520px" tableStyle="font-size:12px">
                    <Column header="代码" frozen style="min-width: 90px">
                        <template #body="{ data }">
                            <router-link class="fs-link"
                                :to="{ name: 'stock-detail', params: { symbol: data.symbol } }">
                                {{ data.symbol }}
                            </router-link>
                        </template>
                    </Column>
                    <Column field="name" header="名称" style="min-width: 100px"/>
                    <Column v-for="col in screenCols" :key="col" :header="factorLabel(col)"
                            style="min-width: 100px">
                        <template #body="{ data }">
                            <span class="fs-num">{{ fmtNum(data[col]) }}</span>
                        </template>
                    </Column>
                    <Column header="操作" frozen alignFrozen="right" style="min-width: 92px">
                        <template #body="{ data }">
                            <Button label="加入池" icon="pi pi-plus" size="small" text
                                    :loading="addingSymbol === data.symbol"
                                    @click="addToPool(data)"/>
                        </template>
                    </Column>
                </DataTable>
            </div>
        </div>

        <!-- ==================== Tab 2 · 信号扫描 ==================== -->
        <div v-else class="fs-pane">
            <div class="fs-panel">
                <div class="fs-panel-h">
                    <span><i class="pi pi-bolt text-blue-500"></i> 信号选择</span>
                </div>
                <div class="fs-signal-grid">
                    <div v-for="s in signalCatalog" :key="s.key" class="fs-signal"
                         :class="{active: signalKey === s.key}" @click="signalKey = s.key">
                        <div class="fs-signal-name">{{ s.label }}</div>
                        <div class="fs-signal-desc">{{ s.desc }}</div>
                    </div>
                </div>
                <div class="fs-actions">
                    <div class="fs-scope">
                        <label class="fs-radio">
                            <input type="radio" value="monitoring" v-model="signalScope"/>
                            监控池
                        </label>
                        <label class="fs-radio">
                            <input type="radio" value="all" v-model="signalScope"/>
                            全库（有因子数据的全部标的）
                        </label>
                    </div>
                    <div class="fs-actions-right">
                        <Button label="开始扫描" icon="pi pi-search" size="small"
                                :loading="signalLoading" @click="runScan"/>
                    </div>
                </div>
            </div>

            <div class="fs-panel" v-if="signalResult">
                <div class="fs-panel-h">
                    <span><i class="pi pi-table text-blue-500"></i> 扫描结果</span>
                    <span class="fs-sub">
                        {{ signalResult.signal_label }} · 命中 <b>{{ signalResult.count }}</b> 只 ·
                        截至 {{ signalResult.asof }}
                    </span>
                </div>
                <div v-if="!signalRows.length" class="fs-empty-hint">
                    当前范围内没有标的触发该信号。可以切到「全库」再试一次。
                </div>
                <DataTable v-else :value="signalRows" :rows="25" paginator
                           :rowsPerPageOptions="[25, 50, 100]" size="small"
                           scrollable scrollHeight="520px" tableStyle="font-size:12px">
                    <Column header="代码" frozen style="min-width: 90px">
                        <template #body="{ data }">
                            <router-link class="fs-link"
                                :to="{ name: 'stock-detail', params: { symbol: data.symbol } }">
                                {{ data.symbol }}
                            </router-link>
                        </template>
                    </Column>
                    <Column field="name" header="名称" style="min-width: 100px"/>
                    <Column v-for="col in signalCols" :key="col" :header="col"
                            style="min-width: 110px">
                        <template #body="{ data }">
                            <span class="fs-num">{{ fmtNum(data[col]) }}</span>
                        </template>
                    </Column>
                    <Column header="操作" frozen alignFrozen="right" style="min-width: 92px">
                        <template #body="{ data }">
                            <Button label="加入池" icon="pi pi-plus" size="small" text
                                    :loading="addingSymbol === data.symbol"
                                    @click="addToPool(data)"/>
                        </template>
                    </Column>
                </DataTable>
            </div>
        </div>
    </div>
</template>

 <style scoped lang="scss">
/* 页面外边距对齐全站约定：横向 2rem（=24px），与 .card 页内容左边缘一致（204）。
   原先写的是 0，面板直接顶到内容区左边缘，和其他页面观感不一致。 */
.fs-wrap {
    padding: 2rem;
}

.fs-tabs {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
}
.fs-tab {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    font-size: 13px;
    border: 0.5px solid rgba(0, 0, 0, 0.12);
    border-radius: 10px;
    background: #fff;
    color: #4a4a4a;
    cursor: pointer;
    transition: all .15s;
}
.fs-tab:hover { border-color: rgba(0, 0, 0, 0.28); }
.fs-tab.active {
    border-color: #d64545;
    color: #d64545;
    box-shadow: 0 0 0 1px rgba(214, 69, 69, 0.18);
}
.fs-tabs-hint {
    font-size: 11px;
    color: #9a9a9a;
    margin-left: auto;
}

.fs-pane { display: flex; flex-direction: column; gap: 14px; }

.fs-panel {
    background: #fff;
    border: 0.5px solid rgba(0, 0, 0, 0.1);
    border-radius: 12px;
    padding: 14px 16px;
}
.fs-panel-h {
    display: flex;
    align-items: baseline;
    gap: 10px;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 12px;
}
.fs-sub { font-size: 11px; font-weight: 400; color: #9a9a9a; }
.fs-sub b { color: #d64545; }

.fs-presets {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
}
.fs-presets-k { font-size: 11px; color: #9a9a9a; }
.fs-preset {
    padding: 4px 10px;
    font-size: 12px;
    border-radius: 12px;
    border: 0.5px solid rgba(0, 0, 0, 0.12);
    background: #fafafa;
    color: #4a4a4a;
    cursor: pointer;
}
.fs-preset:hover { border-color: #d64545; color: #d64545; }

.fs-conds { display: flex; flex-direction: column; gap: 8px; }
.fs-cond {
    display: flex;
    align-items: center;
    gap: 8px;
}
.fs-cond-field { min-width: 240px; flex: 1 1 240px; }
.fs-cond-op { min-width: 150px; flex: 0 0 150px; }
.fs-cond-val { width: 110px; flex: 0 0 110px; }
.fs-cond-unit {
    font-size: 10px;
    color: #a8a8a8;
    white-space: nowrap;
    flex: 0 0 auto;
    min-width: 84px;
}

.fs-empty-hint {
    padding: 10px 0;
    font-size: 12px;
    color: #9a9a9a;
}

.fs-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 12px;
    flex-wrap: wrap;
}
.fs-actions-right { display: flex; align-items: center; gap: 8px; }
.fs-limit-k { font-size: 11px; color: #9a9a9a; }
.fs-limit { width: 84px; }

.fs-preview {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 0.5px dashed rgba(0, 0, 0, 0.1);
    font-size: 12px;
    color: #6b6b6b;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
}
.fs-and { color: #d64545; margin: 0 2px; }
.fs-chip {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    background: #f4f6f9;
    color: #4a4a4a;
    font-size: 11px;
}

.fs-signal-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 10px;
}
.fs-signal {
    border: 0.5px solid rgba(0, 0, 0, 0.12);
    border-radius: 10px;
    padding: 10px 12px;
    cursor: pointer;
    transition: all .15s;
}
.fs-signal:hover { border-color: rgba(0, 0, 0, 0.28); }
.fs-signal.active {
    border-color: #d64545;
    background: #fffafa;
    box-shadow: 0 0 0 1px rgba(214, 69, 69, 0.18);
}
.fs-signal-name { font-size: 13px; font-weight: 500; margin-bottom: 3px; }
.fs-signal-desc { font-size: 11px; color: #9a9a9a; line-height: 1.5; }

.fs-scope { display: flex; gap: 14px; font-size: 12px; color: #4a4a4a; }
.fs-radio { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }

.fs-link { color: #3b82f6; }
.fs-link:hover { text-decoration: underline; }
.fs-num { font-variant-numeric: tabular-nums; }
</style>
