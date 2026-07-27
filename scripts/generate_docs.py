"""批量生成模拟企业文档 — LLM 生成 50 篇 Markdown 文档

用法:
    python scripts/generate_docs.py
    python scripts/generate_docs.py --count 30   # 自定义数量
    python scripts/generate_docs.py --dry-run     # 只看不生成
"""

import os
import time
import argparse
from pathlib import Path
from openai import OpenAI

# 输出目录
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "samples"

# 文档主题池 — 每个主题生成一篇
DOC_TOPICS = [
    # ===== 运维手册 (10篇) =====
    ("运维手册", "MySQL 数据库部署与配置规范"),
    ("运维手册", "Redis 集群搭建与高可用方案"),
    ("运维手册", "Kubernetes Pod 调度策略与资源限制配置"),
    ("运维手册", "Nginx 反向代理与负载均衡配置指南"),
    ("运维手册", "日志采集系统 ELK 搭建与索引优化"),
    ("运维手册", "Prometheus + Grafana 监控告警体系搭建"),
    ("运维手册", "CI/CD 流水线配置规范 (Jenkins/GitLab CI)"),
    ("运维手册", "服务器安全加固基线检查清单"),
    ("运维手册", "数据库备份与灾难恢复预案"),
    ("运维手册", "Docker 镜像构建规范与镜像仓库管理"),

    # ===== 技术规范 (10篇) =====
    ("技术规范", "后端 API 接口设计规范与版本管理策略"),
    ("技术规范", "数据库表设计规范与索引优化原则"),
    ("技术规范", "RESTful API 错误码定义与异常处理标准"),
    ("技术规范", "消息队列使用规范 (Kafka/RabbitMQ 选型与配置)"),
    ("技术规范", "微服务间 RPC 调用超时与重试策略规范"),
    ("技术规范", "缓存使用规范：Redis 缓存策略与击穿防护"),
    ("技术规范", "代码审查标准与提交信息规范"),
    ("技术规范", "SQL 编写规范与慢查询优化指南"),
    ("技术规范", "日志规范：级别定义、格式要求与脱敏规则"),
    ("技术规范", "文件存储规范：对象存储命名规则与生命周期管理"),

    # ===== 管理制度 (10篇) =====
    ("管理制度", "研发中心安全管理制度"),
    ("管理制度", "数据分类分级与访问权限管理办法"),
    ("管理制度", "生产环境变更管理流程与审批制度"),
    ("管理制度", "故障响应与应急处理预案"),
    ("管理制度", "第三方依赖引入评估与审批流程"),
    ("管理制度", "技术债管理制度与重构流程"),
    ("管理制度", "研发环境与生产环境隔离规范"),
    ("管理制度", "外包人员代码访问权限管理办法"),
    ("管理制度", "数据脱敏规范与测试数据管理"),
    ("管理制度", "技术文档编写与维护责任制度"),

    # ===== 故障复盘 (10篇) =====
    ("故障复盘", "订单服务大规模超时故障复盘报告"),
    ("故障复盘", "Redis 内存溢出导致缓存雪崩事故分析"),
    ("故障复盘", "数据库主从延迟引发数据不一致事件复盘"),
    ("故障复盘", "消息队列积压导致订单状态更新延迟复盘"),
    ("故障复盘", "证书过期导致全站 HTTPS 不可用事故分析"),
    ("故障复盘", "代码部署回滚失败导致服务中断复盘"),
    ("故障复盘", "磁盘空间满导致日志丢失事件复盘"),
    ("故障复盘", "限流配置错误导致大面积用户请求被拒复盘"),
    ("故障复盘", "第三方 API 故障导致支付链路中断分析"),
    ("故障复盘", "配置中心配置错误引发灰度环境雪崩复盘"),

    # ===== 产品与需求 (10篇) =====
    ("产品文档", "订单中心系统架构设计与模块说明"),
    ("产品文档", "用户权限管理系统设计文档"),
    ("产品文档", "消息推送平台技术方案"),
    ("产品文档", "实时数据看板系统架构设计"),
    ("产品文档", "开放平台 API 网关设计文档"),
    ("产品文档", "商品库存管理系统的领域模型设计"),
    ("产品文档", "分布式事务方案选型与技术验证报告"),
    ("产品文档", "用户行为埋点方案设计与数据链路"),
    ("产品文档", "服务熔断降级方案设计文档"),
    ("产品文档", "多租户 SaaS 架构设计与数据隔离方案"),
]

SYSTEM_PROMPT = """你是一个企业的技术文档撰写专家。请根据指定的文档类型和标题，生成一篇真实可信的企业内部技术文档。

要求：
1. 格式为 Markdown，包含层级标题、列表、表格和代码块
2. 内容专业、具体，包含真实的配置参数、命令示例、架构描述
3. 文档长度 500-1500 字
4. 使用中文撰写，技术术语保留英文
5. 像真实企业内部文档，不要写"这是一个示例"之类的话
6. 可以包含版本号、变更记录、负责人等字段
7. 直接输出正文，不要写"好的，以下是为您生成的文档："之类的前缀"""


def generate_doc(client: OpenAI, model: str, doc_type: str, title: str, dry_run: bool = False) -> str | None:
    """生成一篇文档"""
    prompt = f"""文档类型：{doc_type}
文档标题：{title}

请生成完整的文档内容："""

    if dry_run:
        print(f"  [DRY RUN] {doc_type}: {title}")
        return None

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=2048,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


def sanitize_filename(title: str) -> str:
    """标题 → 安全的文件名"""
    # 保留中英文数字，其他替换为下划线
    safe = ""
    for c in title:
        if c.isalnum() or c in "_-().":
            safe += c
        elif c == " ":
            safe += "_"
        elif c == "/":
            safe += "_"
        else:
            safe += "_"
    return safe[:60] + ".md"


def main():
    parser = argparse.ArgumentParser(description="生成模拟企业文档")
    parser.add_argument("--count", type=int, default=50, help="生成文档数量 (默认: 50)")
    parser.add_argument("--dry-run", action="store_true", help="只列出主题，不实际生成")
    parser.add_argument("--delay", type=float, default=0.5, help="每篇间隔秒数 (默认: 0.5)")
    args = parser.parse_args()

    # 初始化 LLM
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if not args.dry_run and not api_key:
        # 尝试从 .env 读取
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("DEEPSEEK_API_KEY")

    if not args.dry_run and not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY 环境变量")
        return

    client = OpenAI(api_key=api_key, base_url=base_url) if not args.dry_run else None

    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 取前 N 个主题
    topics = DOC_TOPICS[: min(args.count, len(DOC_TOPICS))]
    if args.count > len(DOC_TOPICS):
        # 超过主题池就循环
        extra = args.count - len(DOC_TOPICS)
        for i in range(extra):
            topics.append(("技术规范", f"企业技术规范补充文档 #{i+1}"))

    print(f"{'[DRY RUN] ' if args.dry_run else ''}准备生成 {len(topics)} 篇文档")
    print(f"输出目录: {OUTPUT_DIR}\n")

    success = 0
    for i, (doc_type, title) in enumerate(topics):
        filename = sanitize_filename(title)
        print(f"[{i+1}/{len(topics)}] {doc_type}: {title}", end=" ", flush=True)

        content = generate_doc(client, model, doc_type, title, args.dry_run)

        if content and not args.dry_run:
            filepath = OUTPUT_DIR / filename
            filepath.write_text(content, encoding="utf-8")
            size = len(content)
            print(f"OK ({size} 字)")
            success += 1
        elif not args.dry_run:
            print("FAIL")
        else:
            print()

        if not args.dry_run and i < len(topics) - 1:
            time.sleep(args.delay)

    print(f"\n完成: {success}/{len(topics)} 篇")
    if success > 0:
        print(f"文件在: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
