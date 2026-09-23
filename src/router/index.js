import AppLayout from '@/layout/AppLayout.vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import { store } from '@/store';

const main_title = 'AlphaLom 一体化金融数据分析与智能投研平台';

const router = createRouter({
    history: createWebHashHistory(),
    routes: [
        {
            path: '/',
            component: AppLayout,
            children: [
                {
                    path: '/',
                    redirect: '/auth/login'
                },
                {
                    path: '/quant/trading_terminal',
                    name: 'trading-terminal',
                    component: () => import('@/views/trading/TradingTerminal.vue'),
                    meta: { title: '量化交易终端', requiresAuth: true, layoutCompact: true } // ⬅️ 关键标记
                },
                {
                    path: '/uikit/market-temperature',
                    name: 'market-temperature',
                    component: () => import('@/views/market/MarketTemperature.vue'),
                    meta: { title: '市场温度计', requiresAuth: true }
                },
                {
                    path: '/market/cn_market_overview',
                    name: 'cn-market-overview',
                    component: () => import('@/views/market/MarketOverview.vue'),
                    meta: { title: '沪深大盘', requiresAuth: true }
                },
                {
                    path: '/market/sector_sentiment',
                    name: 'market-sector-sentiment',
                    component: () => import('@/views/market/SectorSentiment.vue'),
                    meta: { title: '板块情绪', requiresAuth: true }
                },
                {
                    path: '/market/etf_insight',
                    name: 'market-etf-insight',
                    component: () => import('@/views/etf/ETFInsight.vue'),
                    meta: { title: 'ETF洞察', requiresAuth: true }
                },
                {
                    path: '/quant/etf_detail/:symbol',
                    name: 'etf-detail',
                    component: () => import('@/views/etf/ETFDetail.vue'),
                    meta: { title: '个股监控详情', requiresAuth: true }
                },
                {
                    path: '/quant/dcf_insight',
                    name: 'quant-etf-insight',
                    component: () => import('@/views/quant/DCFInsight.vue'),
                    meta: { title: 'DCF估值', requiresAuth: true }
                },
                {
                    path: '/user/watch_list',
                    name: 'user-watch-list',
                    component: () => import('@/views/user/WatchList.vue'),
                    meta: { title: '关注清单', requiresAuth: true }
                },
                {
                    path: '/market/news_flow',
                    name: 'news_flow',
                    component: () => import('@/views/market/NewsFlow.vue'),
                    meta: { title: '事件驱动', requiresAuth: true }
                },
                {
                    path: '/uikit/stocks-pool',
                    name: 'stock-pool',
                    component: () => import('@/views/market/StocksPool.vue'),
                    meta: { title: '股票池', requiresAuth: true }
                },
                {
                    path: '/quant/stock_monitor',
                    name: 'stock-monitor',
                    component: () => import('@/views/stock/StockMonitor.vue'),
                    meta: { title: '个股监控', requiresAuth: true }
                },
                {
                    path: '/quant/stock_detail/:symbol',
                    name: 'stock-detail',
                    component: () => import('@/views/stock/StockDetail.vue'),
                    meta: { title: '个股详情', requiresAuth: true }
                },
                {
                    path: '/quant/trade_signal',
                    name: 'trade_signal',
                    component: () => import('@/views/quant/QuantSignals.vue'),
                    meta: { title: '量化信号', requiresAuth: true }
                },
                {
                    path: '/quant/records',
                    name: 'table',
                    component: () => import('@/views/quant/QuantRecords.vue'),
                    meta: { title: '量化回测记录', requiresAuth: true }
                },
                {
                    path: '/uikit/backtest_setting',
                    name: 'backtest_setting',
                    component: () => import('@/views/uikit/BackTestSetting.vue'),
                    meta: { title: '量化回测设置', requiresAuth: true }
                },
                {
                    path: '/uikit/backtest_detail/:id/:stock_code',
                    name: 'backtest_detail',
                    component: () => import('@/views/quant/BackTestDetail.vue'),
                    meta: { title: '量化回测详情', requiresAuth: true }
                },
                {
                    path: '/uikit/ai_stocks',
                    name: 'ai_stocks',
                    component: () => import('@/views/uikit/AiStocks.vue'),
                    meta: { title: 'AI 热门题材选股', requiresAuth: true }
                },
                {
                    path: '/quant/portfolio_list',
                    name: 'portfolio_list',
                    component: () => import('@/views/portfolios/PortfolioList.vue'),
                    meta: { title: '投资组合', requiresAuth: true }
                },
                {
                    path: '/quant/portfolio_view/:portfolio_id',
                    name: 'portfolio_view',
                    component: () => import('@/views/portfolios/PortfolioView.vue'),
                    meta: { title: '策略组合详情', requiresAuth: true }
                },
                {
                    path: '/quant/portfolio_backtest',
                    name: 'portfolio_backtest',
                    component: () => import('@/views/portfolios/PortfolioBacktest.vue'),
                    meta: { title: '组合回测', requiresAuth: true }
                },
                {
                    path: '/system/llm_setting/',
                    name: 'llm_setting_view',
                    component: () => import('@/views/system/LlmModelSetting.vue'),
                    meta: { title: '大模型配置', requiresAuth: true }
                },
                {
                    path: '/system/system_log/',
                    name: 'system_log_view',
                    component: () => import('@/views/system/SystemLog.vue'),
                    meta: { title: '系统日志', requiresAuth: true }
                },
                {
                    path: '/ai/chat/',
                    name: 'ai_chat_view',
                    component: () => import('@/views/ai/chat.vue'),
                    meta: { title: '智能体', requiresAuth: true }
                }
            ]
        },
        {
            path: '/auth/login',
            name: 'login',
            component: () => import('@/views/auth/Login.vue')
        }
    ],
    scrollBehavior(to, from, savedPosition) {
        // 如果是通过浏览器前进/后退（有 savedPosition），则恢复位置
        if (savedPosition) {
            return savedPosition;
        }
        // 否则，滚动到顶部
        return { top: 0 };
    }
});

// 设置页面标题
router.beforeEach((to, from, next) => {
    if (to.meta.title === undefined) {
        document.title = main_title;
    } else {
        document.title = (to.meta.title + ' - ' + main_title) || main_title;
    }
    // next();
    if (to.matched.some(record => record.meta.requiresAuth)) {
        // 如果目标路由需要认证
        if (!store.getters.isAuthenticated) {
            // 如果用户未认证，重定向到登录页面
            next({ path: '/auth/login' });
        } else {
            // 用户已认证，允许访问
            next();
        }
    } else {
        // 目标路由不需要认证，直接允许访问
        next();
    }
});

export default router;
