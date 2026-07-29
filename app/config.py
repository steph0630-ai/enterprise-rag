"""全局配置，从 .env 读取"""

from pathlib import Path
from pydantic_settings import BaseSettings

# 项目根目录（config.py 在 app/ 下，往上两层）
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # ---- LLM (DeepSeek) ----
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"

    # ---- Embedding (SiliconFlow) ----
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"

    # ---- Vision (Multimodal LLM for image→text) ----
    vision_api_key: str = ""
    vision_base_url: str = "https://api.deepseek.com"
    vision_model: str = "deepseek-chat"

    # ---- Qdrant ----
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_name: str = "enterprise_knowledge"

    # ---- App ----
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ---- Retrieval ----
    retrieval_top_k: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 64

    # ---- 向量维度 (bge-m3 = 1024) ----
    vector_dim: int = 1024

    # ---- NL2SQL ----
    sqlite_db_path: str = ""
    sql_max_rows: int = 200
    sql_timeout_seconds: int = 10

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


_settings: Settings | None = None


def get_settings() -> Settings:
    """获取配置单例（支持热重载：可通过 clear_settings() 重置）"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def clear_settings():
    """清除缓存，强制下次重新加载配置"""
    global _settings
    _settings = None
