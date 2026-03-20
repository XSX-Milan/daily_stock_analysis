# -*- coding: utf-8 -*-
"""
===================================
服务层模块初始化
===================================

职责：
1. 声明可导出的服务类（延迟导入，避免启动时拉入 LLM 等重依赖）

使用方式：
    直接从子模块导入，例如:
    from src.services.history_service import HistoryService
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.analysis_service import AnalysisService
    from src.services.backtest_service import BacktestService
    from src.services.history_service import HistoryService
    from src.services.recommendation_service import RecommendationService
    from src.services.sector_scanner_service import SectorScannerService
    from src.services.stock_service import StockService
    from src.services.task_service import TaskService, get_task_service
    from src.services.watchlist_service import WatchlistService


def __getattr__(name: str):
    """延迟导入：仅在通过 src.services.X 访问时才加载对应子模块。"""
    _lazy_map = {
        "AnalysisService": "src.services.analysis_service",
        "BacktestService": "src.services.backtest_service",
        "HistoryService": "src.services.history_service",
        "SectorScannerService": "src.services.sector_scanner_service",
        "StockService": "src.services.stock_service",
        "TaskService": "src.services.task_service",
        "WatchlistService": "src.services.watchlist_service",
        "get_task_service": "src.services.task_service",
    }
    if name in _lazy_map:
        import importlib

        module = importlib.import_module(_lazy_map[name])
        return getattr(module, name)
    if name == "recommendation_service":
        import importlib

        return importlib.import_module("src.services.recommendation_service")
    if name == "RecommendationService":
        import importlib

        module = importlib.import_module("src.services.recommendation_service")
        return getattr(module, name)
    raise AttributeError(f"module 'src.services' has no attribute {name!r}")


__all__ = [
    "AnalysisService",
    "BacktestService",
    "HistoryService",
    "RecommendationService",
    "SectorScannerService",
    "StockService",
    "TaskService",
    "WatchlistService",
    "get_task_service",
]
