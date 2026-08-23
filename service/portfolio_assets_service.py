"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from sqlalchemy.exc import IntegrityError
from models import PortfolioAssets
from models.database import db_session
from utils.logger import logger


class PortfolioAssetsService:

    @staticmethod
    def add(asset_data):
        """
        @brief 添加一个新的 PortfolioAssets 记录

        @param asset_data: 包含资产数据的字典
        @type asset_data: dict

        @return: 是否成功添加记录
        @rtype: bool

        @throws: IntegrityError 如果插入违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            asset_data = {
                'asset_id': '12345678-1234-5678-1234-567812345678',
                'portfolio_id': '87654321-1234-5678-1234-876543218765',
                'ticker': 'AAPL',
                'asset_name': 'Apple Inc.',
                'sector': 'Technology',
                'position_pct': 10.00,
                'position_price': 150.00,
                'position_size': 10.00
            }
            success = PortfolioAssetsService.add(asset_data)
            print(success)
        """
        try:
            asset = PortfolioAssets(**asset_data)
            db_session.add(asset)
            db_session.commit()
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Insertion failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def batch_add(assets_data):
        """
        @brief 批量添加多个 PortfolioAssets 记录

        @param assets_data: 包含多个资产数据的列表
        @type assets_data: list

        @return: 是否成功批量添加记录
        @rtype: bool

        @throws: IntegrityError 如果插入违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            assets_data = [
                {
                    'asset_id': '12345678-1234-5678-1234-567812345678',
                    'portfolio_id': '87654321-1234-5678-1234-876543218765',
                    'ticker': 'AAPL',
                    'asset_name': 'Apple Inc.',
                    'sector': 'Technology',
                    'position_pct': 10.00,
                    'position_price': 150.00,
                    'position_size': 10.00
                },
                {
                    'asset_id': '87654321-1234-5678-1234-876543218765',
                    'portfolio_id': '12345678-1234-5678-1234-123456781234',
                    'ticker': 'GOOGL',
                    'asset_name': 'Alphabet Inc.',
                    'sector': 'Technology',
                    'position_pct': 15.00,
                    'position_price': 2800.00,
                    'position_size': 5.00
                }
            ]
            success = PortfolioAssetsService.batch_add(assets_data)
            print(success)
        """
        try:
            for asset_data in assets_data:
                asset = PortfolioAssets(**asset_data)
                db_session.add(asset)
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
    def get_all_by_portfolio_id(portfolio_id):
        """
        @brief 根据 portfolio_id 获取 PortfolioAssets 记录

        @param portfolio_id: 资产唯一ID
        @type portfolio_id: str

        @return: 资产记录的字典表示，如果没有找到则返回 None
        @rtype: dict or None

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            asset = PortfolioAssetsService.get_all_by_portfolio_id('1')
            print(asset)
        """
        try:
            asset = db_session.query(PortfolioAssets).filter_by(portfolio_id=portfolio_id).all()
            return [_as.to_dict() for _as in asset]
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        return None

    @staticmethod
    def get_by_symbol(symbol, portfolio_id):
        """
        @brief 根据 asset_id 获取 PortfolioAssets 记录

        @param asset_id: 资产唯一ID
        @type asset_id: str

        @return: 资产记录的字典表示，如果没有找到则返回 None
        @rtype: dict or None

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            asset = PortfolioAssetsService.get_by_asset_id('12345678-1234-5678-1234-567812345678')
            print(asset)
        """
        try:
            asset = db_session.query(PortfolioAssets).filter(
                PortfolioAssets.stock_code==symbol,
                PortfolioAssets.portfolio_id==portfolio_id
            ).first()
            if asset:
                return asset.to_dict()
            else:
                return None
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        return None

    @staticmethod
    def get_by_asset_id(asset_id):
        """
        @brief 根据 asset_id 获取 PortfolioAssets 记录

        @param asset_id: 资产唯一ID
        @type asset_id: str

        @return: 资产记录的字典表示，如果没有找到则返回 None
        @rtype: dict or None

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            asset = PortfolioAssetsService.get_by_asset_id('12345678-1234-5678-1234-567812345678')
            print(asset)
        """
        try:
            asset = db_session.query(PortfolioAssets).filter_by(asset_id=asset_id).first()
            if asset:
                return asset.to_dict()
            else:
                return None
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        return None

    @staticmethod
    def update_by_stock_code(portfolio_id, stock_code, update_data):
        """
        @brief 根据 stock_code 更新 PortfolioAssets 记录

        @param stock_code: 品种代码
        @type stock_code: str
        @param update_data: 包含更新数据的字典
        @type update_data: dict

        @return: 是否成功更新记录
        @rtype: bool

        @throws: IntegrityError 如果更新违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            update_data = {
                'position_pct': 12.00,
                'position_price': 160.00
            }
            success = PortfolioAssetsService.update_by_asset_id('12345678-1234-5678-1234-567812345678', update_data)
            print(success)
        """
        try:
            asset = db_session.query(PortfolioAssets).filter_by(portfolio_id=portfolio_id, stock_code=stock_code).first()
            if asset:
                for key, value in update_data.items():
                    setattr(asset, key, value)
                db_session.commit()
                return True
            else:
                logger.warning(f"Asset with stock_code {stock_code} not found.")
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Update failed: {e}")
        except Exception as e:
            db_session.rollback()
            print(e)
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def update_by_asset_id(asset_id, update_data):
        """
        @brief 根据 asset_id 更新 PortfolioAssets 记录

        @param asset_id: 资产唯一ID
        @type asset_id: str
        @param update_data: 包含更新数据的字典
        @type update_data: dict

        @return: 是否成功更新记录
        @rtype: bool

        @throws: IntegrityError 如果更新违反数据库完整性约束
        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            update_data = {
                'position_pct': 12.00,
                'position_price': 160.00
            }
            success = PortfolioAssetsService.update_by_asset_id('12345678-1234-5678-1234-567812345678', update_data)
            print(success)
        """
        try:
            asset = db_session.query(PortfolioAssets).filter_by(asset_id=asset_id).first()
            if asset:
                for key, value in update_data.items():
                    setattr(asset, key, value)
                db_session.commit()
                return True
            else:
                logger.warning(f"Asset with asset_id {asset_id} not found.")
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Update failed: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def delete_by_asset_id(asset_id):
        """
        @brief 根据 asset_id 删除 PortfolioAssets 记录

        @param asset_id: 资产唯一ID
        @type asset_id: str

        @return: 是否成功删除记录
        @rtype: bool

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            success = PortfolioAssetsService.delete_by_asset_id('12345678-1234-5678-1234-567812345678')
            print(success)
        """
        try:
            asset = db_session.query(PortfolioAssets).filter_by(asset_id=asset_id).first()
            if asset:
                db_session.delete(asset)
                db_session.commit()
                return True
            else:
                logger.warning(f"Asset with asset_id {asset_id} not found.")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False

    @staticmethod
    def delete_zero_by_portfolio_id(portfolio_id):
        """
        @brief 根据 portfolio_id 删除 PortfolioAssets 记录

        @param portfolio_id: 资产唯一ID
        @type portfolio_id: str

        @return: 是否成功删除记录
        @rtype: bool

        @throws: Exception 如果发生其他错误

        @example:
            # 示例用法
            success = PortfolioAssetsService.delete_by_asset_id('12345678-1234-5678-1234-567812345678')
            print(success)
        """
        try:
            asset = db_session.query(PortfolioAssets).filter(
                PortfolioAssets.portfolio_id == portfolio_id,
                PortfolioAssets.position_size == 0
            ).first()
            if asset:
                db_session.delete(asset)
                db_session.commit()
                return True
            else:
                logger.warning(f"Asset with portfolio_id {portfolio_id} not found.")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An error occurred: {e}")
        return False
