"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

智能体（LlmAgent）表的迁移脚本（幂等，可重复执行）。

功能：
- 新建 `llm_agent` 表（如果不存在）
- 插入几条默认智能体（归属到 guest / id=2），仅首次运行有效

用法：
    # 先看会做什么，不动库
    .venv/Scripts/python.exe install/migrate_llm_agent.py --dry-run

    # 正式执行
    .venv/Scripts/python.exe install/migrate_llm_agent.py

⚠️ 所有操作幂等 —— 跑第二遍不做任何改动。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from models import LlmAgent, Base  # noqa: E402
from models.database import engine  # noqa: E402

DEFAULT_OWNER_USER_ID = 2  # guest（存量归属账号）

# ---------- 默认智能体数据 ----------

DEFAULT_AGENTS = [
    {
        'name': '量化助手',
        'emoji': '📊',
        'platform': 'deepseek',
        'model': 'deepseek-v4-flash',
        'system_prompt': '你是一个量化交易金融机构的专家，请以JSON格式输出。',
    },
    {
        'name': '代码助手',
        'emoji': '💻',
        'platform': 'volcengine',
        'model': 'qwen3.6-plus',
        'system_prompt': '你是一个编程专家，擅长多种语言。',
    },
]


def _table_exists(conn, table: str) -> bool:
    """检查表是否存在。"""
    return conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    ), {'t': table}).scalar() > 0


def main():
    parser = argparse.ArgumentParser(description='智能体表迁移（幂等）')
    parser.add_argument('--owner-user-id', type=int, default=DEFAULT_OWNER_USER_ID,
                        help=f'默认智能体归属的 user id（默认 {DEFAULT_OWNER_USER_ID}）')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要执行的操作，不改库')
    args = parser.parse_args()

    print(f'=== 智能体表迁移：owner_user_id={args.owner_user_id} dry_run={args.dry_run} ===')

    with engine.begin() as conn:
        users = conn.execute(text('SELECT id, username FROM users ORDER BY id')).fetchall()
        print(f'现有用户：{users}')
        if args.owner_user_id not in {r[0] for r in users}:
            print(f'❌ owner_user_id={args.owner_user_id} 不是有效用户，终止')
            return 1

        # Step 1: 建表
        print('[1/2] 检查并创建 llm_agent 表...')
        if _table_exists(conn, 'llm_agent'):
            print('    llm_agent 表已存在，跳过建表')
        else:
            print('    [建表] CREATE TABLE llm_agent ...')
            if not args.dry_run:
                Base.metadata.create_all(bind=conn, checkfirst=True)
            print('    ✅ 表创建完成')

        # Step 2: 插入默认智能体（幂等，同用户同名不重复）
        print('[2/2] 插入默认智能体（若已存在则跳过）...')
        inserted_count = 0
        for agent in DEFAULT_AGENTS:
            count = conn.execute(text(
                "SELECT COUNT(*) FROM llm_agent WHERE user_id = :u AND name = :n"
            ), {'u': args.owner_user_id, 'n': agent['name']}).scalar()
            if count > 0:
                print(f'    ⏭️  "{agent["name"]}" 已存在，跳过')
                continue
            if not args.dry_run:
                conn.execute(text(
                    "INSERT INTO llm_agent (user_id, name, emoji, platform, model, system_prompt, created_at) "
                    "VALUES (:u, :n, :e, :p, :m, :s, NOW())"
                ), {
                    'u': args.owner_user_id,
                    'n': agent['name'],
                    'e': agent['emoji'],
                    'p': agent['platform'],
                    'm': agent['model'],
                    's': agent['system_prompt'],
                })
            print(f'    ✅ 插入 "{agent["name"]}" ({agent["platform"]} / {agent["model"]})')
            inserted_count += 1

        print(f'    本次插入 {inserted_count} 条默认智能体')

    print('=== 迁移结束 ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
