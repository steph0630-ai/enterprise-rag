"""NL2SQL 数据库管理器 — 管理用户上传的多个 SQLite 数据库，支持切换"""

import logging
import sqlite3
from pathlib import Path

from app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DATABASES_DIR = PROJECT_ROOT / "data" / "databases"
DEFAULT_DB = PROJECT_ROOT / "data" / "business.db"


class DatabaseManager:
    """管理多个 SQLite 数据库，支持增删切换"""

    def __init__(self):
        self.databases_dir = DATABASES_DIR
        self.databases_dir.mkdir(parents=True, exist_ok=True)
        self._active_db: str | None = None  # filename of active db
        self._db_info_cache: dict[str, dict] = {}

    @property
    def active_db(self) -> str | None:
        """当前活跃的数据库文件名"""
        return self._active_db

    @property
    def active_db_path(self) -> str | None:
        """当前活跃的数据库完整路径"""
        if self._active_db:
            path = self.databases_dir / self._active_db
            if path.exists():
                return str(path)

        # 回退到默认数据库
        if DEFAULT_DB.exists():
            return str(DEFAULT_DB)
        return None

    def list_databases(self) -> list[dict]:
        """列出所有已上传的数据库及其表信息"""
        dbs = []
        if self.databases_dir.exists():
            for f in sorted(self.databases_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".db3"}:
                    info = self.get_database_info(f.name)
                    dbs.append(info)

        # 默认数据库也列出来
        if DEFAULT_DB.exists():
            already = any(d["filename"] == DEFAULT_DB.name for d in dbs)
            if not already:
                info = self.get_database_info(DEFAULT_DB.name)
                if info:
                    dbs.insert(0, info)

        return dbs

    def get_database_info(self, filename: str) -> dict | None:
        """获取单个数据库的信息"""
        # 判断路径
        if filename == DEFAULT_DB.name and DEFAULT_DB.exists():
            path = str(DEFAULT_DB)
        else:
            path = str(self.databases_dir / filename)

        if not Path(path).exists():
            return None

        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            table_names = [t[0] for t in tables]

            # 统计每张表的行数（采样估算，大表不精确计数）
            table_row_counts = {}
            for t in table_names:
                try:
                    cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                    table_row_counts[t] = cnt
                except Exception:
                    table_row_counts[t] = 0

            conn.close()

            size = Path(path).stat().st_size

            return {
                "filename": filename,
                "path": path,
                "size_bytes": size,
                "tables": table_names,
                "table_details": table_row_counts,
            }
        except Exception as e:
            logger.error("Failed to read db %s: %s", filename, e)
            return {
                "filename": filename,
                "path": path,
                "size_bytes": Path(path).stat().st_size if Path(path).exists() else 0,
                "tables": [],
                "table_details": {},
            }

    def add_database(self, filename: str, file_path: str):
        """注册一个数据库"""
        self._db_info_cache.pop(filename, None)

    def remove_database(self, filename: str):
        """移除一个数据库"""
        self._db_info_cache.pop(filename, None)
        if self._active_db == filename:
            self._active_db = None

    def switch_database(self, filename: str):
        """切换到指定数据库"""
        # 先验证数据库可读
        path = self.databases_dir / filename
        if not path.exists() and filename != DEFAULT_DB.name:
            raise FileNotFoundError(f"数据库文件不存在: {filename}")

        actual_path = str(path) if path.exists() else str(DEFAULT_DB)
        try:
            conn = sqlite3.connect(f"file:{actual_path}?mode=ro", uri=True)
            conn.close()
        except sqlite3.Error as e:
            raise ValueError(f"无法打开数据库 {filename}: {e}")

        self._active_db = filename
        # 清除 NL2SQL pipeline 缓存，强制重建
        _reset_nl2sql_pipeline()
        logger.info("Database switched to: %s (%s)", filename, actual_path)

    def reset_active(self):
        """重置活跃数据库（恢复到默认）"""
        self._active_db = None
        _reset_nl2sql_pipeline()


# ── 全局单例 ──

_db_manager: DatabaseManager | None = None


def get_db_manager() -> DatabaseManager:
    """获取 DatabaseManager 单例"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_active_db_path() -> str | None:
    """获取当前活跃数据库的路径（供 NL2SQL pipeline 使用）"""
    return get_db_manager().active_db_path


def _reset_nl2sql_pipeline():
    """重置 NL2SQL pipeline 缓存"""
    # 通过 chat 模块的 reset 函数触发重建
    import app.api.chat as chat_module
    if hasattr(chat_module, 'reset_nl2sql'):
        chat_module.reset_nl2sql()
