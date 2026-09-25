"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

持仓行业分布饼图 依赖的 `stock_industry` 表：建表 + 回填（幂等，可重复执行）。

背景：
    组合持仓可能包含监控池（stocks 表）之外的票，而 `stocks.industry` 只覆盖监控池内票，
    导致 `enrich_assets_with_industry` 关联不上、饼图一堆「其他」。
    本表以 symbol 为主键，作为「股票→行业」的权威映射，覆盖池内+池外所有出现过的票。

功能：
    1. 新建 `stock_industry` 表（不存在才建）
    2. 收集所有组合持仓里出现过的 stock_code
    3. 对每个 code，优先取 `stocks.industry`，缺失则调 databull 公司资料拉取，upsert 进本表
    4. 顺带把监控池内票的 industry 也同步进来（覆盖全量）

用法：
    .venv/Scripts/python.exe install/migrate_stock_industry.py --dry-run
    .venv/Scripts/python.exe install/migrate_stock_industry.py

⚠️ 拉取行业会访问 databull（网络）。跑之前若环境有代理干扰，先 unset HTTP_PROXY/HTTPS_PROXY。
⚠️ 幂等：已存在 symbol 不会重复插入；若想刷新行业，删对应行或整表后重跑。
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from models import Stock, StockIndustry, Base  # noqa: E402
from models.database import engine, db_session  # noqa: E402

# databull 需要的环境变量（如有代理先清掉，否则「第 1 个请求 200、之后全 404」）
for _p in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_p, None)


def _table_exists(conn, table: str) -> bool:
    return conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    ), {'t': table}).scalar() > 0


def _collect_codes(conn):
    """收集组合持仓里出现过的所有股票代码。"""
    rows = conn.execute(text(
        "SELECT DISTINCT stock_code FROM portfolio_assets WHERE stock_code IS NOT NULL AND stock_code <> ''"
    )).fetchall()
    return [r[0] for r in rows]


def _ensure_table(conn, dry_run):
    if _table_exists(conn, 'stock_industry'):
        print('    stock_industry 表已存在，跳过建表')
        return
    print('    [建表] CREATE TABLE stock_industry ...')
    if not dry_run:
        Base.metadata.create_all(bind=conn, checkfirst=True)
    print('    ✅ 表创建完成')


def _upsert(conn, dry_run, symbol, industry, source):
    exists = conn.execute(text(
        "SELECT COUNT(*) FROM stock_industry WHERE symbol = :s"
    ), {'s': symbol}).scalar() > 0
    if exists:
        # 已有且行业非空则跳过；为空则补上
        cur = conn.execute(text(
            "SELECT industry FROM stock_industry WHERE symbol = :s"
        ), {'s': symbol}).scalar()
        if cur:
            return 'skip'
        if not dry_run:
            conn.execute(text(
                "UPDATE stock_industry SET industry = :i, source = :src, update_time = NOW() WHERE symbol = :s"
            ), {'i': industry, 'src': source, 's': symbol})
        return 'update'
    if not dry_run:
        conn.execute(text(
            "INSERT INTO stock_industry (symbol, industry, market, source, update_time) "
            "VALUES (:s, :i, 'cn', :src, NOW())"
        ), {'s': symbol, 'i': industry, 'src': source})
    return 'insert'


def main():
    parser = argparse.ArgumentParser(description='stock_industry 建表+回填（幂等）')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要执行的操作，不改库')
    args = parser.parse_args()

    print(f'=== stock_industry 迁移：dry_run={args.dry_run} ===')

    with engine.begin() as conn:
        # Step 1: 建表
        print('[1/3] 检查并创建 stock_industry 表...')
        _ensure_table(conn, args.dry_run)

        # Step 2: 收集持仓代码 + 监控池代码
        print('[2/3] 收集需回填的股票代码...')
        codes = _collect_codes(conn)
        # 监控池内票也同步（让映射表覆盖全量，未来新组合直接命中）
        pool_rows = conn.execute(text(
            "SELECT DISTINCT symbol FROM stocks WHERE industry IS NOT NULL AND industry <> ''"
        )).fetchall()
        pool_codes = {r[0]: r[0] for r in pool_rows}
        from_stocks = {}
        for r in pool_rows:
            from_stocks[r[0]] = conn.execute(text(
                "SELECT industry FROM stocks WHERE symbol = :s"
            ), {'s': r[0]}).scalar()
        all_codes = list(dict.fromkeys(codes + list(from_stocks.keys())))
        print(f'    持仓去重 {len(codes)} 个，监控池有行业 {len(from_stocks)} 个，合计 {len(all_codes)} 个')

        # Step 3: 逐个回填
        print('[3/3] 逐个回填行业...')
        stats = {'insert': 0, 'update': 0, 'skip': 0, 'fail': 0}
        for sym in all_codes:
            # 优先用 stocks.industry
            ind = from_stocks.get(sym)
            src = 'stocks'
            if not ind:
                try:
                    from service.stock import StockService
                    fields = StockService.company_profile_fields(sym, 'cn')
                    ind = fields.get('industry')
                    src = 'databull'
                except Exception as e:
                    print(f'    ⚠️  {sym} 拉取失败：{type(e).__name__} {str(e)[:80]}')
                    stats['fail'] += 1
                    continue
            if not ind:
                stats['fail'] += 1
                continue
            res = _upsert(conn, args.dry_run, sym, ind, src)
            stats[res] = stats.get(res, 0) + 1

        print(f'    结果：新增 {stats["insert"]} / 更新 {stats["update"]} / 跳过 {stats["skip"]} / 失败 {stats["fail"]}')

    print('=== 迁移结束 ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
