"""种子数据脚本 — 创建 SQLite 数据库并填充电商经营数据

运行方式: python data/seed_data.py
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "business.db"


def seed():
    # 如果数据库已存在，删除重建
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    # ──────────────────────────────────────────
    # 1. 商品表
    # ──────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit_price REAL NOT NULL,
            monthly_sales INTEGER NOT NULL,
            monthly_revenue REAL NOT NULL,
            inventory INTEGER NOT NULL,
            cost_price REAL,
            supplier TEXT,
            created_at TEXT DEFAULT '2024-01-01'
        )
    """)

    products = [
        ("无线蓝牙耳机 Pro", "数码配件", 199, 3200, 636800, 850, 120, "深圳声学科技"),
        ("便携充电宝 20000mAh", "数码配件", 89, 5600, 498400, 1200, 52, "深圳电池科技"),
        ("手机支架 铝合金", "数码配件", 35, 8900, 311500, 3000, 18, "东莞五金厂"),
        ("数据线 Type-C 1米", "数码配件", 19.9, 15000, 298500, 5000, 8.5, "深圳线缆科技"),
        ("蓝牙音箱 便携款", "数码配件", 149, 1800, 268200, 420, 85, "深圳声学科技"),
        ("笔记本散热支架", "电脑周边", 79, 2200, 173800, 680, 45, "东莞五金厂"),
        ("机械键盘 青轴", "电脑周边", 299, 500, 149500, 200, 180, "广州外设科技"),
        ("鼠标 无线静音", "电脑周边", 59, 2300, 135700, 900, 32, "广州外设科技"),
        ("显示器支架 双臂", "电脑周边", 249, 450, 112050, 150, 150, "东莞五金厂"),
        ("USB集线器 7口", "电脑周边", 45, 2000, 90000, 1100, 25, "深圳线缆科技"),
    ]

    cursor.executemany(
        """INSERT INTO products
           (name, category, unit_price, monthly_sales, monthly_revenue, inventory, cost_price, supplier)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        products,
    )

    # ──────────────────────────────────────────
    # 2. 广告投放表
    # ──────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE ad_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            spend REAL NOT NULL,
            impressions INTEGER NOT NULL,
            clicks INTEGER NOT NULL,
            conversions INTEGER NOT NULL,
            ctr REAL GENERATED ALWAYS AS (clicks * 100.0 / impressions) STORED,
            cpc REAL GENERATED ALWAYS AS (spend / clicks) STORED,
            roi REAL GENERATED ALWAYS AS ((conversions * 80.0) / spend) STORED,
            start_date TEXT DEFAULT '2024-07-01',
            end_date TEXT DEFAULT '2024-07-31'
        )
    """)

    campaigns = [
        ("抖音", 50000, 800000, 24000, 1200),
        ("小红书", 30000, 500000, 18000, 900),
        ("百度搜索", 20000, 200000, 12000, 600),
        ("微信朋友圈", 15000, 300000, 9000, 400),
    ]

    cursor.executemany(
        """INSERT INTO ad_campaigns (channel, spend, impressions, clicks, conversions)
           VALUES (?, ?, ?, ?, ?)""",
        campaigns,
    )

    # ──────────────────────────────────────────
    # 3. 物流成本表
    # ──────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE shipping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier TEXT NOT NULL,
            order_share_percent REAL NOT NULL,
            avg_cost_per_order REAL NOT NULL,
            monthly_orders INTEGER NOT NULL,
            monthly_total_cost REAL NOT NULL,
            month TEXT DEFAULT '2024-07'
        )
    """)

    shipping = [
        ("圆通", 60.0, 4.0, 25170, 100680),
        ("申通", 30.0, 4.5, 12585, 56632),
        ("顺丰", 10.0, 5.0, 4195, 20975),
    ]

    cursor.executemany(
        """INSERT INTO shipping (carrier, order_share_percent, avg_cost_per_order, monthly_orders, monthly_total_cost)
           VALUES (?, ?, ?, ?, ?)""",
        shipping,
    )

    # ──────────────────────────────────────────
    # 4. 月度汇总表
    # ──────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE monthly_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            total_revenue REAL NOT NULL,
            total_orders INTEGER NOT NULL,
            return_rate REAL NOT NULL,
            repurchase_rate REAL NOT NULL,
            gross_margin REAL NOT NULL,
            total_cost REAL,
            net_profit REAL
        )
    """)

    summary = [
        ("2024-06", 2453600, 38100, 2.3, 26.0, 34.5, 1600000, 850000),
        ("2024-07", 2674450, 41950, 2.1, 28.0, 35.0, 1738000, 936450),
    ]

    cursor.executemany(
        """INSERT INTO monthly_summary
           (month, total_revenue, total_orders, return_rate, repurchase_rate, gross_margin, total_cost, net_profit)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        summary,
    )

    # ──────────────────────────────────────────
    # 5. 退货记录表
    # ──────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            return_count INTEGER NOT NULL,
            return_reason TEXT,
            return_date TEXT DEFAULT '2024-07'
        )
    """)

    returns = [
        (1, "无线蓝牙耳机 Pro", 67, "音质不达预期"),
        (2, "便携充电宝 20000mAh", 118, "容量虚标"),
        (3, "手机支架 铝合金", 187, "做工粗糙"),
        (4, "数据线 Type-C 1米", 315, "接触不良"),
        (5, "蓝牙音箱 便携款", 38, "连接不稳定"),
        (6, "笔记本散热支架", 46, "噪音大"),
        (7, "机械键盘 青轴", 11, "不喜欢青轴手感"),
        (8, "鼠标 无线静音", 48, "偶尔断连"),
        (9, "显示器支架 双臂", 9, "安装复杂"),
        (10, "USB集线器 7口", 42, "接口松动"),
    ]

    cursor.executemany(
        """INSERT INTO returns (product_id, product_name, return_count, return_reason)
           VALUES (?, ?, ?, ?)""",
        returns,
    )

    conn.commit()
    conn.close()

    print(f"[OK] Database created: {DB_PATH}")
    print(f"     Size: {DB_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    seed()
