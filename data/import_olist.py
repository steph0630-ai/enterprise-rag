"""将 Brazilian E-Commerce CSV 导入 SQLite

使用方法:
    1. 把下面 CSV_DIR 改成你解压 CSV 的文件夹路径
    2. 运行: python data/import_olist.py
"""

import csv
import sqlite3
import re
from pathlib import Path

# ⚠️ 把下面这行改成你解压 CSV 的文件夹路径
CSV_DIR = Path("d:\\Users\\86191\\Desktop\\archive")

# 输出数据库路径（一般不用改）
DB_PATH = Path(__file__).resolve().parent / "business.db"


def safe_column_name(name: str) -> str:
    """把 CSV 列名转成 SQLite 安全的列名"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().strip())


def infer_type(values: list[str]) -> str:
    """根据样本值推断 SQLite 列类型"""
    non_empty = [v for v in values if v and v.strip()]
    if not non_empty:
        return "TEXT"
    sample = non_empty[0]
    try:
        int(sample)
        return "INTEGER"
    except ValueError:
        pass
    try:
        float(sample)
        return "REAL"
    except ValueError:
        pass
    if re.match(r"\d{4}-\d{2}-\d{2}", sample):
        return "TEXT"
    return "TEXT"


def import_csv_to_sqlite(csv_path: Path, conn: sqlite3.Connection):
    """导入单个 CSV 到 SQLite"""
    table_name = csv_path.stem.replace("olist_", "").replace("_dataset", "")
    print(f"  -> {table_name}...", end=" ", flush=True)

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        columns = [safe_column_name(c) for c in header]

        sample_rows = []
        for i, row in enumerate(reader):
            if i < 1000:
                sample_rows.append(row)

    col_types = []
    for i, _col in enumerate(columns):
        samples = [r[i] if i < len(r) else "" for r in sample_rows]
        col_types.append(infer_type(samples))

    col_defs = [f'"{col}" {t}' for col, t in zip(columns, col_types)]
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})')

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        placeholders = ", ".join(["?" for _ in columns])
        col_names = ", ".join([f'"{c}"' for c in columns])
        batch = []
        for row in reader:
            padded = list(row) + [None] * (len(columns) - len(row))
            batch.append(padded[:len(columns)])
            if len(batch) >= 10000:
                conn.executemany(
                    f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
                    batch,
                )
                batch = []
        if batch:
            conn.executemany(
                f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
                batch,
            )

    conn.commit()
    row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
    print(f"{row_count} rows OK")


def main():
    print("=" * 50)
    print("Brazilian E-Commerce -> SQLite")
    print("=" * 50)

    if not CSV_DIR.exists():
        print(f"\nERROR: Folder not found: {CSV_DIR}")
        print("Open import_olist.py and change CSV_DIR to the folder")
        print("where you extracted the CSV files.")
        return

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    csv_order = [
        "olist_sellers_dataset.csv",
        "olist_customers_dataset.csv",
        "olist_products_dataset.csv",
        "product_category_name_translation.csv",
        "olist_orders_dataset.csv",
        "olist_order_items_dataset.csv",
        "olist_order_payments_dataset.csv",
        "olist_order_reviews_dataset.csv",
    ]

    print("\nImporting...")
    for csv_file in csv_order:
        csv_path = CSV_DIR / csv_file
        if csv_path.exists():
            import_csv_to_sqlite(csv_path, conn)

    conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nDone: {DB_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
