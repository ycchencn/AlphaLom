"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

ETF 轮动池（etf_rotation_pool）建表迁移脚本（幂等，可重复执行）。

背景：「ETF 洞察」页新增轮动分析页签，参与轮动的 ETF 需要**独立于监控列表**单独维护
（见 models.EtfRotationPool 的类注释，说明为什么没复用 etf_watchlist）。

用法：
    # 先看会做什么，不动库
    .venv/Scripts/python.exe install/migrate_etf_rotation_pool.py --dry-run

    # 建表
    .venv/Scripts/python.exe install/migrate_etf_rotation_pool.py

⚠️ 三条约束（与 migrate_multi_user.py 一致）：
  1. **只新建**，绝不 ALTER / DROP 既有表 —— 本脚本不碰任何存量数据；
  2. 幂等 —— 表已存在则直接跳过（checkfirst），跑第二遍不做任何改动；
  3. DDL 前设 `lock_wait_timeout`，避免建表等元数据锁时把全站查询堵住。

实现说明：DDL 由 `Base.metadata.create_all(tables=[...])` 从**模型定义直接生成**，
而不是手写 CREATE TABLE —— 手写副本会随模型漂移（加字段忘了改脚本），这是历史上
`install/database.sql` 与模型对不上的根因。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from models import Base, EtfRotationPool  # noqa: E402
from models.database import engine  # noqa: E402

LOCK_WAIT_TIMEOUT = 5   # 等元数据锁的秒数上限，超时即放弃（不硬等）


def _describe(conn, table: str) -> None:
    """打印表的列与索引，用于「建完确认真的长成预期」而不是只看脚本没报错。"""
    rows = conn.execute(text(
        'SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE FROM information_schema.COLUMNS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION'
    ), {'t': table}).fetchall()
    print(f'    列（{len(rows)}）：')
    for name, col_type, nullable in rows:
        print(f'      - {name} {col_type} {"NULL" if nullable == "YES" else "NOT NULL"}')

    idx = conn.execute(text(
        'SELECT INDEX_NAME, NON_UNIQUE, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) '
        'FROM information_schema.STATISTICS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t '
        'GROUP BY INDEX_NAME, NON_UNIQUE ORDER BY INDEX_NAME'
    ), {'t': table}).fetchall()
    print(f'    索引（{len(idx)}）：')
    for name, non_unique, cols in idx:
        kind = '普通' if non_unique else '唯一'
        print(f'      - {kind} {name} ({cols})')


def main():
    parser = argparse.ArgumentParser(description='ETF 轮动池建表迁移（幂等）')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要执行的操作，不改库')
    args = parser.parse_args()

    table = EtfRotationPool.__tablename__
    print(f'=== ETF 轮动池迁移：table={table} dry_run={args.dry_run} ===')

    with engine.begin() as conn:
        # 建表本身也是 DDL，同样可能等元数据锁
        conn.execute(text(f'SET SESSION lock_wait_timeout = {LOCK_WAIT_TIMEOUT}'))

        if inspect(conn).has_table(table):
            print(f'[跳过] {table} 已存在，不做任何改动')
            _describe(conn, table)
            print('=== 完成（无改动） ===')
            return

        print(f'[建表] {table}（DDL 来自 models.EtfRotationPool）')
        if args.dry_run:
            from sqlalchemy.schema import CreateTable, CreateIndex
            print(CreateTable(EtfRotationPool.__table__).compile(engine))
            # ⚠️ 索引不在 CREATE TABLE 里 —— create_all 会另外执行 CREATE INDEX。
            # 只打印 CreateTable 会让人以为 index=True 的列没建索引，故一并列出。
            for ix in sorted(EtfRotationPool.__table__.indexes, key=lambda i: i.name):
                print(CreateIndex(ix).compile(engine))
            print('=== dry-run 结束，未改库 ===')
            return

        Base.metadata.create_all(bind=conn, tables=[EtfRotationPool.__table__], checkfirst=True)

    # 另开连接复查：建表在刚才的事务里已提交，这里能看到真实结果
    with engine.connect() as conn:
        if not inspect(conn).has_table(table):
            print(f'[失败] {table} 仍未存在，请检查数据库权限')
            sys.exit(1)
        _describe(conn, table)
        print('=== 完成 ===')


if __name__ == '__main__':
    main()
