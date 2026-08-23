"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import akshare as ak
import pandas as pd
import os
from datetime import datetime, timedelta

"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from models import IndexConstituents
from flask import current_app
from models.database import db_session
from sqlalchemy.exc import SQLAlchemyError
from utils.logger import logger
from datetime import date
from typing import List, Optional

class IndexConstituentsService:

    @staticmethod
    def create(_index_code: str, stock_code: str = None, stock_name: str = None, add_date=None):
        """
        创建一条指数成分股记录。

        :param _index_code: 指数代码（必填）
        :param stock_code: 股票代码（可选，建议传入6位字符串）
        :param stock_name: 股票名称（可选，建议传入6位字符串）
        :param add_date: 纳入日期（可为 date 对象、字符串 'YYYY-MM-DD' 或 None）
        :return: 成功返回 IndexConstituents 实例，失败返回 None
        """
        try:
            # 处理 add_date：支持 str 或 date
            if isinstance(add_date, str):
                from datetime import datetime
                add_date = datetime.strptime(add_date, '%Y-%m-%d').date()
            elif add_date is not None and not isinstance(add_date, date):
                add_date = None  # 忽略非法类型

            # 确保 index_code 为字符串
            _index_code = str(_index_code)
            stock_code = str(stock_code) if stock_code is not None else None

            new_record = IndexConstituents(
                index_code=_index_code,
                stock_name=stock_name,
                stock_code=stock_code,
                add_date=add_date
            )
            db_session.add(new_record)
            db_session.commit()
            return new_record
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error occurred while creating index constituent: {e}")
            db_session.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error in IndexConstituentsService.create: {e}")
            db_session.rollback()
            return None

    @staticmethod
    def bulk_create(records: List[dict]):
        """
        批量插入指数成分股记录。
        :param records: 列表，每个元素为 dict，包含 index_code, stock_code, add_date
        :return: 成功插入数量，失败返回 None
        """
        try:
            objs = []
            for r in records:
                # 确保 stock_code 为字符串（防止 int 导致前导零丢失）
                stock_code = str(r.get('stock_code')) if r.get('stock_code') is not None else None
                add_date = r.get('add_date')
                if isinstance(add_date, str):
                    from datetime import datetime
                    add_date = datetime.strptime(add_date, '%Y-%m-%d').date()
                elif not isinstance(add_date, date) and add_date is not None:
                    add_date = None

                obj = IndexConstituents(
                    index_code=str(r['index_code']),
                    stock_code=stock_code,
                    add_date=add_date
                )
                objs.append(obj)

            db_session.bulk_save_objects(objs)
            db_session.commit()
            return len(objs)
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error during bulk create index constituents: {e}")
            db_session.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error in bulk_create: {e}")
            db_session.rollback()
            return None

    @staticmethod
    def get_by_index_code(index_code: str, page: int = 1, page_size: int = 100) -> dict:
        """
        分页查询指定指数的成分股。
        :param index_code: 指数代码（如 '000905'）
        :param page: 页码（从1开始）
        :param page_size: 每页数量
        :return: {'items': [...], 'total': int, 'page': int, 'page_size': int, 'has_more': bool}
        """
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 5000:
            page_size = 100

        try:
            query = db_session.query(IndexConstituents).filter(
                IndexConstituents.index_code == index_code
            )
            total = query.count()
            items = (
                query
                .order_by(IndexConstituents.add_date.desc(), IndexConstituents.stock_code)
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [item.to_dict() for item in items],
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": (page * page_size) < total
            }
        except Exception as e:
            logger.error(f"Error fetching constituents for index {index_code}: {e}")
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "has_more": False
            }

    @staticmethod
    def delete_by_index_code(index_code: str) -> bool:
        """
        删除某个指数的所有成分股记录（用于更新前清空）。
        :param index_code: 指数代码
        :return: 是否成功
        """
        try:
            deleted_count = db_session.query(IndexConstituents).filter(
                IndexConstituents.index_code == index_code
            ).delete(synchronize_session=False)
            db_session.commit()
            logger.info(f"Deleted {deleted_count} records for index {index_code}")
            return True
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error deleting constituents for {index_code}: {e}")
            db_session.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error in delete_by_index_code: {e}")
            db_session.rollback()
            return False

    @staticmethod
    def get_latest_update_date(index_code: str) -> Optional[date]:
        """
        获取某指数最新成分股的 add_date（用于判断是否需要更新）。
        :param index_code: 指数代码
        :return: 最新日期或 None
        """
        try:
            latest = (
                db_session.query(IndexConstituents.add_date)
                .filter(IndexConstituents.index_code == index_code)
                .order_by(IndexConstituents.add_date.desc())
                .first()
            )
            return latest[0] if latest else None
        except Exception as e:
            logger.error(f"Error getting latest update date for {index_code}: {e}")
            return None

    @staticmethod
    def get_index_constituents_with_cache(index_code="000905", cache_file="_cache.csv", expire_days=30):
        """
        获取指数成分股，支持自动缓存（默认缓存30天）

        Parameters:
            index_code (str): 指数编码，如 "000905"（中证500）
            cache_file (str): 缓存文件名后缀
            expire_days (int): 缓存有效期（天）

        Returns:
            pd.DataFrame: 成分股列表，stock_code 为6位字符串
        """
        now = datetime.now()
        full_cache_path = f"../cache/{index_code}{cache_file}"

        # 确保缓存目录存在
        os.makedirs(os.path.dirname(full_cache_path), exist_ok=True)

        # 尝试加载缓存
        if os.path.exists(full_cache_path):
            file_mtime = datetime.fromtimestamp(os.path.getmtime(full_cache_path))
            if now - file_mtime < timedelta(days=expire_days):
                print(f"使用缓存文件：{full_cache_path}（上次更新于 {file_mtime.strftime('%Y-%m-%d %H:%M:%S')}）")
                return pd.read_csv(full_cache_path, dtype={"stock_code": str})
            else:
                print("缓存已过期，正在重新获取最新数据...")
        else:
            print("未找到缓存文件，正在获取最新数据...")

        # 获取最新数据
        try:
            df = ak.index_stock_cons(symbol=index_code)
        except Exception as e:
            raise RuntimeError(f"获取指数 {index_code} 成分股失败: {e}")

        field_mapping = {
            "品种名称": "stock_name",
            "品种代码": "stock_code",
            "纳入日期": "add_date"
        }

        df.rename(columns=field_mapping, inplace=True)

        # 保存缓存
        df.to_csv(full_cache_path, index=False, encoding="utf-8-sig")
        print(f"✅ 已更新缓存文件：{full_cache_path}（共 {len(df)} 只股票）")
        return df

# 使用示例
if __name__ == "__main__":

    pass
