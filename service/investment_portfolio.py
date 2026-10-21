"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models import (
    InvestmentPortfolio, PortfolioAssets, DailyPnLRecord,
    PortfolioDailySummary, PortfolioTransaction,
)
from models.database import db_session
from utils.logger import logger


def as_portfolio_id(value):
    """
    归一化 portfolio_id。

    线上 `investment_portfolio.portfolio_id` 是 int，而路由的路径参数声明成 str
    （`/investment_portfolios_info/{portfolio_id}`），子表里的同名列又是 varchar ——
    用同一个值去比 int 列和 varchar 列时，类型不一致会让 MySQL 做隐式转换，
    既可能走不上索引，也可能出现「字符串 '2 ' 匹配不到 2」这类意外。
    这里统一转成 int 再进查询；转不动（脏数据）时原样返回，交给数据库比较。
    """
    if isinstance(value, bool) or value is None:
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


class InvestmentPortfolioService:

    @staticmethod
    def add(portfolio_data):
        """
        @brief 添加一个新的 InvestmentPortfolio 记录

        @param portfolio_data: 包含投资组合数据的字典
        @type portfolio_data: dict

        @return: 成功返回新组合的 portfolio_id（由数据库自增分配）；失败返回 None
        @rtype: int or None

        ⚠️ 返回值语义在 2026-09-24 多用户改造时从 `bool` 改成「新 id / None」：
        主键改由数据库自增分配后，调用方（POST /investment_portfolios）必须把新 id
        回给前端，否则前端建完组合拿不到 id、跳转详情页无从下手。
        唯一调用点是 `routes/portfolio.py`。
        ⚠️ **不要**再往 portfolio_data 里塞 'portfolio_id'：线上主键是
        `int AUTO_INCREMENT`，塞 uuid 会被非严格模式静默截断成 0。
        """
        try:
            portfolio = InvestmentPortfolio(**portfolio_data)
            db_session.add(portfolio)
            db_session.commit()
            return portfolio.portfolio_id
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Insertion failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return None

    @staticmethod
    def batch_add(portfolios_data):
        """
        @brief 批量添加多个 InvestmentPortfolio 记录

        @param portfolios_data: 包含多个投资组合数据的列表
        @type portfolios_data: list

        @return: 是否成功批量添加记录
        @rtype: bool

        @throws: IntegrityError 如果插入违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            portfolios_data = [
                {
                    'portfolio_id': '12345678-1234-5678-1234-567812345678',
                    'name': 'My Portfolio 1',
                    'total_position_pct': 80.00,
                    'base_currency': 'USD'
                },
                {
                    'portfolio_id': '87654321-1234-5678-1234-876543218765',
                    'name': 'My Portfolio 2',
                    'total_position_pct': 90.00,
                    'base_currency': 'EUR'
                }
            ]
            success = InvestmentPortfolioService.batch_add(portfolios_data)
            print(success)
        """
        try:
            for portfolio_data in portfolios_data:
                portfolio = InvestmentPortfolio(**portfolio_data)
                db_session.add(portfolio)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Batch insertion failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def get_by_portfolio_id(portfolio_id):
        """
        @brief 根据 portfolio_id 获取 InvestmentPortfolio 记录

        @param portfolio_id: 投资组合唯一ID
        @type portfolio_id: str

        @return: 投资组合记录的字典表示，如果没有找到则返回 None
        @rtype: dict or None

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            portfolio = InvestmentPortfolioService.get_by_portfolio_id('12345678-1234-5678-1234-567812345678')
            print(portfolio)
        """
        try:
            portfolio = db_session.query(InvestmentPortfolio).filter_by(
                portfolio_id=as_portfolio_id(portfolio_id)).first()
            if portfolio:
                return portfolio.to_dict()
            else:
                return None
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        return None

    @staticmethod
    def update_by_portfolio_id(portfolio_id, update_data):
        """
        @brief 根据 portfolio_id 更新 InvestmentPortfolio 记录

        @param portfolio_id: 投资组合唯一ID
        @type portfolio_id: str
        @param update_data: 包含更新数据的字典
        @type update_data: dict

        @return: 是否成功更新记录
        @rtype: bool

        @throws: IntegrityError 如果更新违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            update_data = {
                'name': 'Updated Portfolio Name',
                'total_position_pct': 85.00
            }
            success = InvestmentPortfolioService.update_by_portfolio_id('12345678-1234-5678-1234-567812345678', update_data)
            print(success)
        """
        try:
            portfolio = db_session.query(InvestmentPortfolio).filter_by(
                portfolio_id=as_portfolio_id(portfolio_id)).first()
            if portfolio:
                for key, value in update_data.items():
                    setattr(portfolio, key, value)
                db_session.commit()
                return True
            else:
                logger.warning(f"InvestmentPortfolio with portfolio_id {portfolio_id} not found.")
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Update failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def _related_tables(portfolio_id):
        """策略的 4 张关联子表及其查询参数。

        ⚠️ 子表的 `portfolio_id` 列类型与主表**不一致**（`portfolio_assets` /
        `daily_pnl_records` / `portfolio_daily_summary` 是 varchar，`portfolio_transaction`
        是 int），所以必须按各列真实类型分别传参：给 varchar 列传 int 会触发 MySQL
        隐式转换，既走不上索引也可能匹配到意外的值。
        """
        pid_int = as_portfolio_id(portfolio_id)
        return [
            ('assets', PortfolioAssets, PortfolioAssets.portfolio_id, str(pid_int)),
            ('daily_pnl', DailyPnLRecord, DailyPnLRecord.portfolio_id, str(pid_int)),
            ('daily_summary', PortfolioDailySummary, PortfolioDailySummary.portfolio_id, str(pid_int)),
            ('transactions', PortfolioTransaction, PortfolioTransaction.portfolio_id, pid_int),
        ]

    @staticmethod
    def delete_related(portfolio_id) -> dict:
        """删除某策略在 4 张关联子表里的全部数据。

        ⚠️ 这几张表与主表之间**没有外键**（`portfolio_assets.portfolio_id` 是 varchar(36)、
        主表是 int，类型本就不兼容，线上也确实没有 FK 约束），数据库不会级联。
        只删主表会留下永久孤儿：净值曲线、交易记录再也关联不到任何策略，却仍会被
        `get_last_by_portfolio_id` 这类查询扫到。

        ⚠️ 只做 `delete()` 不 commit —— 由调用方与主表删除放在同一个事务里提交，
        保证「主表删了子表没删」这种半截状态不会出现。
        """
        stats = {}
        for key, model, col, val in InvestmentPortfolioService._related_tables(portfolio_id):
            stats[key] = int(db_session.query(model).filter(col == val)
                             .delete(synchronize_session=False) or 0)
        return stats

    @staticmethod
    def delete_with_related(portfolio_id):
        """删除策略本体 + 全部关联子表数据（同一事务，任一步失败整体回滚）。

        @param portfolio_id: 投资组合唯一ID
        @type portfolio_id: str

        @return: (是否删除成功, 各子表被清理的行数统计)
        @rtype: (bool, dict)

        @example:
            # 示例用法
            ok, stats = InvestmentPortfolioService.delete_with_related(8)
            print(ok, stats)      # True, {'assets': 5, 'daily_pnl': 120, ...}
        """
        try:
            portfolio = db_session.query(InvestmentPortfolio).filter_by(
                portfolio_id=as_portfolio_id(portfolio_id)).first()
            if not portfolio:
                logger.warning(f"InvestmentPortfolio with portfolio_id {portfolio_id} not found.")
                return False, {}
            stats = InvestmentPortfolioService.delete_related(portfolio_id)
            db_session.delete(portfolio)
            db_session.commit()
            return True, stats
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred while deleting portfolio {portfolio_id}: {e}")
            return False, {}

    @staticmethod
    def delete_by_portfolio_id(portfolio_id):
        """
        @brief 根据 portfolio_id 删除 InvestmentPortfolio 记录及其全部关联子表数据

        ⚠️ 2026-10-18：从「只删主表」升级为级联清理（持仓 / 每日盈亏 / 每日汇总 / 交易记录）。
        这几张表没有外键，原实现会在库里留下永久孤儿数据。

        @param portfolio_id: 投资组合唯一ID
        @type portfolio_id: str

        @return: 是否成功删除记录
        @rtype: bool

        @throws: Exception 如果发生其他错误（内部已捕获并回滚）

        @example:
            # 示例用法
            success = InvestmentPortfolioService.delete_by_portfolio_id(8)
            print(success)
        """
        ok, _ = InvestmentPortfolioService.delete_with_related(portfolio_id)
        return ok

    @staticmethod
    def get_all(enable=1, fields=None, user_id=None):
        """
        获取投资组合。

        :param enable: 启用状态筛选
        :param fields: 需要返回的字段列表，如 ['id', 'name', 'total_assets']，为None时返回全部字段
        :param user_id: 只返回该用户的组合；**为 None 时返回全部用户的组合**
                        （定时任务是替所有用户跑的，必须拿到全量 —— 见下面注释）

        ⚠️ `user_id=None` 不等于「默认用户」，而是「不限用户」：
          - Web 接口**必须显式传**当前用户 id（隔离）；
          - `job_position_plan_daily_all` / `run_daily_strategy_all` 这类定时任务
            刻意不传，它们要遍历所有用户的组合逐个跑（任务本身没有用户上下文，
            这也不该是缺陷 —— 行情/调仓是按组合算的）。
        """
        query = db_session.query(InvestmentPortfolio).filter(
            InvestmentPortfolio.enable == enable
        )
        if user_id is not None:
            query = query.filter(InvestmentPortfolio.user_id == int(user_id))
        if fields:
            # 构建要查询的实体列表
            columns = [getattr(InvestmentPortfolio, f) for f in fields]
            query = query.with_entities(*columns)
            # 执行查询，结果不再为 ORM 对象而是 Row 或 NamedTuple
            rows = query.all()
            # 转换为字典列表
            return [dict(zip(fields, row)) for row in rows]
        else:
            stocks = query.all()
            return [stock.to_dict() for stock in stocks]
