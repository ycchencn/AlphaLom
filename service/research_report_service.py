"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import and_

# 假设模型和会话已导入
# 请根据实际项目结构调整导入路径
from models import ResearchReport
from models.database import db_session  # 假设这是全局会话或会话工厂
from utils.logger import logger


class ResearchReportService:

    @staticmethod
    def add(report_data: Dict[str, Any]) -> Optional[ResearchReport]:
        """
        添加单条研报数据
        :param report_data: 包含研报字段的字典
        :return: 成功返回 ResearchReport 对象，失败返回 None
        """
        # 1. 预检查：防止重复入库 (基于 file_hash)
        if report_data.get('file_hash'):
            if ResearchReportService.exists_by_hash(report_data['file_hash']):
                logger.warning(f"Report with hash {report_data['file_hash']} already exists, skipping.")
                return None

        try:
            report = ResearchReport(**report_data)
            db_session.add(report)
            db_session.commit()
            # 刷新对象以获取自增 ID 和其他默认值
            db_session.refresh(report)
            logger.info(f"Report added successfully: ID={report.id}, Title={report.title}")
            return report
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Insertion failed due to integrity error: {e}")
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"Database error occurred: {e}")
        except Exception as e:
            db_session.rollback()
            logger.error(f"An unexpected error occurred: {e}")
        return None

    @staticmethod
    def batch_add(report_data_list: List[Dict[str, Any]]) -> bool:
        """
        批量添加研报数据
        :param report_data_list: 包含多个研报数据字典的列表
        :return: 成功返回 True，失败返回 False
        """
        if not report_data_list:
            return True

        try:
            # 可选：在批量插入前进行简单的去重过滤 (基于内存或简单查询)
            # 这里为了性能，直接尝试插入，依靠数据库唯一索引或应用层前置过滤

            # ✅ 使用 bulk_insert_mappings：高效、低内存、绕过 ORM 实例化开销
            db_session.bulk_insert_mappings(ResearchReport, report_data_list)
            db_session.commit()
            logger.info(f"Batch insertion successful. Count: {len(report_data_list)}")
            return True
        except IntegrityError as e:
            db_session.rollback()
            logger.error(f"Batch insertion failed due to integrity error: {e}")
            return False
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"Database error during batch insertion: {e}")
            return False
        except Exception as e:
            db_session.rollback()
            logger.error(f"Unexpected error during batch insertion: {e}")
            return False

    @staticmethod
    def get_by_code(stock_code: str, report_type: int) -> Optional[ResearchReport]:
        """
        根据 ID 查询单个研报
        """
        try:
            report = db_session.query(ResearchReport).filter(
                ResearchReport.stock_code==stock_code,
                ResearchReport.report_type==report_type
            ).order_by(ResearchReport.created_at.desc()).first()
            return report.to_dict() if report else None
        except Exception as e:
            logger.error(f"Error fetching report by ID {stock_code}: {e}")
            return None

    @staticmethod
    def exists_by_hash(file_hash: str) -> bool:
        """
        检查文件哈希是否存在
        """
        if not file_hash:
            return False
        try:
            count = db_session.query(ResearchReport).filter_by(file_hash=file_hash).count()
            return count > 0
        except Exception as e:
            logger.error(f"Error checking hash existence: {e}")
            return False

    @staticmethod
    def query_reports(
        stock_code: Optional[str] = None,
        broker_name: Optional[str] = None,
        report_type: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        rating: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ResearchReport]:
        """
        通用查询方法，支持多条件组合筛选
        :param stock_code: 股票代码
        :param broker_name: 券商名称 (支持模糊匹配)
        :param report_type: 研报类型 (1-个股, 2-行业, 3-宏观)
        :param start_time: 开始时间
        :param end_time: 结束时间
        :param rating: 评级 (支持模糊匹配)
        :param limit: 返回数量限制
        :param offset: 偏移量
        :return: 研报列表
        """
        try:
            query = db_session.query(ResearchReport)

            # 构建动态查询条件
            conditions = []

            if stock_code:
                conditions.append(ResearchReport.stock_code == stock_code)

            if broker_name:
                # 模糊匹配券商名称
                conditions.append(ResearchReport.broker_name.like(f"%{broker_name}%"))

            if report_type is not None:
                conditions.append(ResearchReport.report_type == report_type)

            if start_time:
                conditions.append(ResearchReport.publish_time >= start_time)

            if end_time:
                conditions.append(ResearchReport.publish_time <= end_time)

            if rating:
                conditions.append(ResearchReport.rating.like(f"%{rating}%"))

            if conditions:
                query = query.filter(and_(*conditions))

            # 默认排序：发布时间倒序
            query = query.order_by(ResearchReport.publish_time.desc())

            # 分页
            results = query.offset(offset).limit(limit).all()
            return results

        except Exception as e:
            logger.error(f"Error querying reports: {e}")
            return []

    @staticmethod
    def get_statistics(stock_code: Optional[str] = None, broker_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取简单的统计信息 (示例)
        """
        try:
            query = db_session.query(ResearchReport)
            if stock_code:
                query = query.filter_by(stock_code=stock_code)
            if broker_name:
                query = query.filter_by(broker_name=broker_name)

            total_count = query.count()

            # 获取最新发布时间
            latest_report = query.order_by(ResearchReport.publish_time.desc()).first()
            latest_time = latest_report.publish_time if latest_report else None

            return {
                "total_count": total_count,
                "latest_publish_time": latest_time.isoformat() if latest_time else None
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {"total_count": 0, "latest_publish_time": None}
