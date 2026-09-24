"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

多用户改造的数据库迁移脚本（幂等，可重复执行）。

背景：改造前「股票池 / 量化策略 / ETF 自选」都是**全局单份**，且各自被一个全局唯一键
卡死（`stocks.symbol`、`investment_portfolio.name`、`etf_watchlist.symbol`），
两个用户无法各存各的。本脚本负责把表结构调整成支持按用户隔离，并把存量数据
统一归到一个账号名下（默认 guest / id=2）。

用法：
    # 先看会做什么，不动库
    .venv/Scripts/python.exe install/migrate_multi_user.py --dry-run

    # 只跑股票池那两步（Phase 1）
    .venv/Scripts/python.exe install/migrate_multi_user.py --steps pool

    # 全部（Phase 1+2+3；**不含** users 邮箱索引）
    .venv/Scripts/python.exe install/migrate_multi_user.py --steps all --owner-user-id 2

    # ⚠️ 单独跑：给 users.email 加唯一索引（「用户名或邮箱」登录需要）。
    #    这条会给 users 表加排他锁、可能堵住登录查询，务必挑没人用的时间跑。
    .venv/Scripts/python.exe install/migrate_multi_user.py --steps users

⚠️ 三条硬约束：
  1. 所有步骤幂等 —— 跑第二遍不做任何改动（先查 information_schema 再决定动不动 DDL）；
  2. 任何 ALTER 之前先 `CREATE TABLE ..._mu_bak_<日期>` 备份原表（数据量都很小）；
  3. 只调整「结构 + 归属」，不改业务字段值。存量数据一律归 owner，
     不按 `monitor_by` 之类的文本标签猜归属（那些标签是批次名，不是用户名）。
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from models import Base  # noqa: E402
from models.database import engine  # noqa: E402
from utils.logger import logger  # noqa: E402

DEFAULT_OWNER_USER_ID = 2      # guest（与用户确认过的存量归属账号）
BACKUP_SUFFIX_TAG = 'mu_bak'   # 备份表名前缀标记
LOCK_WAIT_TIMEOUT = 5          # DDL 等元数据锁的秒数上限，超时即放弃（见 step_users_email_unique）


# ==================== 小工具 ====================

def _table_exists(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _index_names(conn, table: str) -> dict:
    """返回 {索引名: [列名, ...]}（按 SEQ_IN_INDEX 排序）"""
    rows = conn.execute(text(
        "SELECT INDEX_NAME, COLUMN_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t "
        "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
    ), {'t': table}).fetchall()
    result = {}
    for name, column in rows:
        result.setdefault(name, []).append(column)
    return result


def _has_unique_on(conn, table: str, columns: list) -> bool:
    """是否存在一个「恰好由这些列组成」的唯一索引（顺序敏感）"""
    indexes = _index_names(conn, table)
    for name, cols in indexes.items():
        if cols == columns:
            non_unique = conn.execute(text(
                "SELECT NON_UNIQUE FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i LIMIT 1"
            ), {'t': table, 'i': name}).scalar()
            if not non_unique:
                return True
    return False


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
    ), {'t': table, 'c': column}).scalar() > 0


def _row_count(conn, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return conn.execute(text(f'SELECT COUNT(*) FROM `{table}`')).scalar() or 0


def _backup(conn, table: str, dry_run: bool) -> str:
    """把表整表复制一份做备份（数据量小，直接 CREATE TABLE AS）。已存在则跳过。"""
    backup = f'{table}_{BACKUP_SUFFIX_TAG}_{datetime.now().strftime("%Y%m%d")}'
    if _table_exists(conn, backup):
        print(f'    [备份] {backup} 已存在，跳过')
        return backup
    print(f'    [备份] {table} -> {backup}（{_row_count(conn, table)} 行）')
    if not dry_run:
        conn.execute(text(f'CREATE TABLE `{backup}` AS SELECT * FROM `{table}`'))
    return backup


def _exec(conn, sql: str, dry_run: bool):
    print(f'    [SQL] {sql}')
    if not dry_run:
        conn.execute(text(sql))


# ==================== 步骤 ====================

def step_pool_create_tables(conn, owner_id: int, dry_run: bool):
    """① 建出缺失的表（只会新建不存在的，已存在的表不会被改动）"""
    print('[1/2] 建缺失表（user_stock_pool 等）')
    if dry_run:
        missing = [t.name for t in Base.metadata.sorted_tables
                   if not _table_exists(conn, t.name)]
        print(f'    [DRY] 预期新建: {missing or "（无）"}')
        return
    # ⚠️ 必须复用当前连接（bind=conn），不要 bind=engine：
    # create_all 走另一条连接时，新建的表在当前事务（REPEATABLE READ）的读快照里
    # **看不见**，紧接着的回填步骤会以为「表不存在」而静默跳过。
    Base.metadata.create_all(bind=conn, checkfirst=True)
    print(f'    user_stock_pool 存在 = {_table_exists(conn, "user_stock_pool")}')


def step_pool_backfill(conn, owner_id: int, dry_run: bool):
    """② 把存量股票池（stocks.monitoring=1）归到 owner 名下"""
    print(f'[2/2] 回填 user_stock_pool：把 stocks.monitoring=1 归给 user_id={owner_id}')
    if not _table_exists(conn, 'user_stock_pool'):
        print('    user_stock_pool 不存在，跳过（先跑步骤 ①）')
        return

    existing = conn.execute(text(
        'SELECT COUNT(*) FROM user_stock_pool WHERE user_id = :u'), {'u': owner_id}).scalar()
    if existing:
        print(f'    owner 名下已有 {existing} 条，视为已回填，跳过（幂等）')
        return

    total = conn.execute(text('SELECT COUNT(*) FROM stocks WHERE monitoring = 1')).scalar()
    print(f'    待回填 {total} 条')
    if dry_run:
        print('    [DRY] INSERT IGNORE INTO user_stock_pool ... SELECT ... FROM stocks WHERE monitoring=1')
        return

    # INSERT IGNORE：万一有重复（(user_id, symbol) 唯一键）也不报错中断
    conn.execute(text(
        'INSERT IGNORE INTO user_stock_pool (user_id, symbol, market, monitor_by, created_at) '
        'SELECT :u, symbol, IFNULL(market, "cn"), monitor_by, NOW() '
        'FROM stocks WHERE monitoring = 1'
    ), {'u': owner_id})
    after = conn.execute(text(
        'SELECT COUNT(*) FROM user_stock_pool WHERE user_id = :u'), {'u': owner_id}).scalar()
    print(f'    回填完成：owner 名下有 {after} 条')


def step_etf_add_user_id(conn, owner_id: int, dry_run: bool):
    """③ etf_watchlist 加 user_id，唯一键 symbol -> (user_id, symbol)，存量归 owner"""
    print(f'[ETF] etf_watchlist 加 user_id 并把唯一键改成 (user_id, symbol)，存量归 user_id={owner_id}')
    table = 'etf_watchlist'
    if not _table_exists(conn, table):
        print('    表不存在，跳过')
        return

    if not _column_exists(conn, table, 'user_id'):
        _backup(conn, table, dry_run)
        _exec(conn, f'ALTER TABLE `{table}` ADD COLUMN `user_id` INT NULL '
                    f"COMMENT 'owner user id (users.id)'", dry_run)
        _exec(conn, f'ALTER TABLE `{table}` ADD INDEX `ix_etf_watchlist_user_id` (`user_id`)', dry_run)
    else:
        print('    user_id 列已存在，跳过加列')

    # 存量归属
    if not dry_run:
        updated = conn.execute(text(
            f'UPDATE `{table}` SET user_id = :u WHERE user_id IS NULL'), {'u': owner_id}).rowcount
        print(f'    存量归属：更新 {updated} 行')
    else:
        print('    [DRY] UPDATE etf_watchlist SET user_id = owner WHERE user_id IS NULL')

    # 唯一键：symbol -> (user_id, symbol)
    if not _has_unique_on(conn, table, ['user_id', 'symbol']):
        for name, cols in _index_names(conn, table).items():
            if cols == ['symbol']:
                _exec(conn, f'ALTER TABLE `{table}` DROP INDEX `{name}`', dry_run)
        _exec(conn, f'ALTER TABLE `{table}` ADD UNIQUE KEY `uniq_user_symbol` (`user_id`, `symbol`)', dry_run)
    else:
        print('    (user_id, symbol) 唯一键已存在，跳过')

    # 回填后 user_id 不应再有 NULL
    if not dry_run:
        nulls = conn.execute(text(f'SELECT COUNT(*) FROM `{table}` WHERE user_id IS NULL')).scalar()
        print(f'    剩余 user_id 为 NULL 的行：{nulls}')


def step_portfolio_scope(conn, owner_id: int, dry_run: bool):
    """④ investment_portfolio：存量组合整体归 owner + name 唯一键改成 (uid, name)"""
    print(f'[策略] investment_portfolio: 存量组合归 user_id={owner_id}，唯一键 name -> (uid, name)')
    table = 'investment_portfolio'
    if not _table_exists(conn, table):
        print('    表不存在，跳过')
        return

    # ⚠️ 用「唯一键是否已改为复合」当**一次性标记**，而不是「uid 是否为空」：
    # 线上 uid 早就有值（1 / 5），且 uid=5 指向的是**已被删除的旧用户**（users 表只有 1、2），
    # 属于悬空值 —— 根本不能沿用。这次迁移要把存量组合**整体收编**给 owner，
    # 所以必须整体覆盖而不是「只补 NULL」。
    # 反过来，如果按「uid != owner 就改」来写，第二次运行时会把用户后来新建的组合
    # 抢到 owner 名下。所以这里用 DDL 是否已执行作为闸门：只做一次。
    if _has_unique_on(conn, table, ['uid', 'name']):
        print('    (uid, name) 唯一键已存在 → 视为已迁移，跳过（幂等）')
        return

    rows = conn.execute(text(f'SELECT uid, COUNT(*) FROM `{table}` GROUP BY uid')).fetchall()
    print(f'    迁移前 uid 分布：{rows}')
    if not dry_run:
        users = {r[0] for r in conn.execute(text('SELECT id FROM users')).fetchall()}
        dangling = [uid for uid, _ in rows if uid is None or uid not in users]
        if dangling:
            print(f'    ⚠️ 悬空/空 uid {dangling}（指向不存在的用户）→ 一并收编')
        updated = conn.execute(text(
            f'UPDATE `{table}` SET uid = :u'), {'u': owner_id}).rowcount
        print(f'    存量组合全部归到 user_id={owner_id}，更新 {updated} 行')
        after = conn.execute(text(f'SELECT uid, COUNT(*) FROM `{table}` GROUP BY uid')).fetchall()
        print(f'    迁移后 uid 分布：{after}')
    else:
        print(f'    [DRY] UPDATE {table} SET uid = {owner_id}（全部存量行）')

    _backup(conn, table, dry_run)
    for name, cols in _index_names(conn, table).items():
        if cols == ['name']:
            _exec(conn, f'ALTER TABLE `{table}` DROP INDEX `{name}`', dry_run)
    _exec(conn, f'ALTER TABLE `{table}` ADD UNIQUE KEY `uniq_uid_name` (`uid`, `name`)', dry_run)


def step_users_email_unique(conn, owner_id: int, dry_run: bool):
    """
    ⑤ users：邮箱归一化 + 加唯一索引（邮箱也是登录凭证）。

    ⚠️⚠️ 这一步**不在 `--steps all` 里**，必须显式 `--steps users` 才会跑。原因：
    `ALTER TABLE users ADD UNIQUE KEY` 要求 users 的**排他元数据锁**，而线上/开发库
    长期存在「Sleep 但事务没结束」的连接（它们持有共享 MDL）。ALTER 一旦进入 MDL
    队列，**排在它后面的所有 users 读请求都会被堵住**——实测把登录接口（`SELECT
    users...`）堵了 250 秒以上，等于全站登不进。所以：
      1. 用 `lock_wait_timeout` 给 DDL 一个短超时（见 LOCK_WAIT_TIMEOUT），
         超时就放弃，绝不让它无限期拖住整表读；
      2. 失败只打印警告、不抛异常：不影响其它步骤，也不留半成品。

    邮箱唯一性的**实际保障是应用层的 `UserService.email_exists`**（建号/改号前
    校验，这两条写路径只有管理员能走）。DB 唯一索引只是加固，加不上不影响正确性。

    归一化三件事：去空格、转小写、空值写 NULL。
      - 大小写：列是 utf8mb4_bin（区分大小写）→ 不归一化就查不到自己的邮箱；
      - 空串：唯一索引下**多个空串会被判成重复**，而「不填邮箱」是正常的，
        所以空值必须写 NULL（MySQL 允许多个 NULL）。
    """
    print('[用户] users: 邮箱归一化（trim + lower，空串→NULL）+ 加唯一索引 uniq_email')
    table = 'users'
    if not _table_exists(conn, table):
        print('    表不存在，跳过')
        return

    if _has_unique_on(conn, table, ['email']):
        print('    email 唯一索引已存在 → 视为已迁移，跳过（幂等）')
        return

    # ⚠️ 先「用查询模拟归一化后的结果」查重，**不要先 UPDATE 再查**：
    # 万一有重复，事务里已经改过的数据会跟着回滚/或被误提交，白折腾一轮。
    conflicts = conn.execute(text(
        "SELECT LOWER(TRIM(email)) AS e, COUNT(*) AS n FROM users "
        "WHERE email IS NOT NULL AND TRIM(email) <> '' "
        "GROUP BY e HAVING n > 1"
    )).fetchall()
    if conflicts:
        print(f'    ❌ 存在归一化后重复的邮箱 {conflicts}，无法加唯一索引')
        print('       请先在用户管理页把重复邮箱改成唯一值（或清空），再重跑本步骤')
        return

    print(f'    归一化前：{conn.execute(text("SELECT id, username, email FROM users ORDER BY id")).fetchall()}')
    if not dry_run:
        blank = conn.execute(text(
            "UPDATE users SET email = NULL WHERE email IS NOT NULL AND TRIM(email) = ''")).rowcount
        lowered = conn.execute(text(
            "UPDATE users SET email = LOWER(TRIM(email)) WHERE email IS NOT NULL")).rowcount
        print(f'    空串→NULL {blank} 行，trim+lower {lowered} 行')
        print(f'    归一化后：{conn.execute(text("SELECT id, username, email FROM users ORDER BY id")).fetchall()}')
    else:
        print('    [DRY] UPDATE users SET email = NULL/LOWER(TRIM(email)) ...')

    _backup(conn, table, dry_run)
    if dry_run:
        _exec(conn, f'ALTER TABLE `{table}` ADD UNIQUE KEY `uniq_email` (`email`)', dry_run)
        return

    try:
        conn.execute(text(f'SET SESSION lock_wait_timeout = {LOCK_WAIT_TIMEOUT}'))
        conn.execute(text(f'ALTER TABLE `{table}` ADD UNIQUE KEY `uniq_email` (`email`)'))
        print('    ✅ 已加上唯一索引 uniq_email')
    except Exception as e:
        print(f'    ⚠️ 加唯一索引失败，已跳过（{type(e).__name__}: {e}）')
        print('       users 表上多半有未结束的事务占着元数据锁（本环境很常见）。')
        print('       邮箱唯一性由应用层 email_exists 保证，不影响登录与建号；')
        print('       想补上：等这些连接结束（重启相关服务）后再单独跑 --steps users。')


STEP_GROUPS = {
    'pool': [step_pool_create_tables, step_pool_backfill],
    'etf': [step_etf_add_user_id],
    'portfolio': [step_portfolio_scope],
    'users': [step_users_email_unique],
}
# ⚠️ 'users' 刻意**不并入 all**：它是唯一一个对 users 表加排他 DDL 的步骤，
# 会阻塞登录查询（详见 step_users_email_unique 的说明）。要跑就显式 --steps users。
STEP_GROUPS['all'] = (STEP_GROUPS['pool'] + STEP_GROUPS['etf']
                      + STEP_GROUPS['portfolio'])


def main():
    parser = argparse.ArgumentParser(description='多用户改造迁移（幂等）')
    parser.add_argument('--owner-user-id', type=int, default=DEFAULT_OWNER_USER_ID,
                        help=f'存量数据归属的 user id（默认 {DEFAULT_OWNER_USER_ID}）')
    parser.add_argument('--steps', default='all',
                        choices=['all', 'pool', 'etf', 'portfolio', 'users'],
                        help='要执行的步骤组')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要执行的操作，不改库')
    args = parser.parse_args()

    print(f'=== 多用户迁移：steps={args.steps} owner_user_id={args.owner_user_id} '
          f'dry_run={args.dry_run} ===')

    if not args.dry_run:
        with engine.begin() as conn:
            users = conn.execute(text('SELECT id, username FROM users ORDER BY id')).fetchall()
            print(f'现有用户：{users}')
            if args.owner_user_id not in {r[0] for r in users}:
                print(f'❌ owner_user_id={args.owner_user_id} 不是有效用户，终止')
                return 1

    # ⚠️ 每个步骤单独一个事务：跨连接（或上一步刚做完）的 DDL 在当前事务的读快照里
    # 不可见，一个长事务跑完全部步骤会让后续步骤看到旧结构而静默跳过。
    for step in STEP_GROUPS[args.steps]:
        with engine.begin() as conn:
            step(conn, args.owner_user_id, args.dry_run)
        print('')

    print('=== 迁移结束 ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
