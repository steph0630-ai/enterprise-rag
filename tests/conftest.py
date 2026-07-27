"""共享 fixtures — 所有测试文件自动加载"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def sample_db_path():
    """指向已建好的 SQLite 测试数据库"""
    db_path = PROJECT_ROOT / "data" / "business.db"
    if not db_path.exists():
        pytest.fail(f"测试数据库不存在: {db_path}，请先运行 python data/seed_data.py")
    return str(db_path)


@pytest.fixture
def temp_db_path():
    """临时数据库（用于测试 executor 的行为，不污染真实数据）"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def sample_docs_dir():
    return PROJECT_ROOT / "docs" / "samples"


@pytest.fixture
def markdown_content():
    return """# 测试文档

## 第一节

这是第一节的内容。包含一些测试文本。

## 第二节

这是第二节的内容。包含更多测试文本。

### 子章节

这是子章节的内容。
"""


@pytest.fixture
def sample_chunks():
    """模拟分块结果"""
    return [
        {"content": "这是第一个文档片段，关于订单服务部署。", "chunk_index": 0},
        {"content": "订单服务默认超时时间是 30 秒。", "chunk_index": 1},
        {"content": "订单服务监听 8080 端口，需要配置环境变量。", "chunk_index": 2},
        {"content": "Redis 部署需要配置最大内存和持久化策略。", "chunk_index": 3},
        {"content": "API 接口返回状态码 200 表示成功。", "chunk_index": 4},
    ]
