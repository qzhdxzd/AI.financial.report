#!/usr/bin/env python3
"""
每日自动运行脚本 - Claw 数字员工核心调度入口
==============================================
用于 cron / systemd timer / 任务计划程序 每日定时调用。
执行完整流水线：新闻采集 → 打分 → 分析 → 报告生成 → 存档

用法:
    # 完整运行（使用 DeepSeek 筛选）
    python run_daily.py

    # 模拟模式（使用示例新闻，不访问网络）
    python run_daily.py --mock

    # 指定输出目录
    python run_daily.py --output-dir data/reports

    # 仅采集新闻，不生成报告
    python run_daily.py --collect-only

    # 指定个股代码
    python run_daily.py --stock 000977

cron 配置示例（每个交易日 18:00 执行）:
    0 18 * * 1-5 cd /path/to/AI.financial.report && python run_daily.py >> logs/daily.log 2>&1
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


def setup_logging():
    """配置日志目录"""
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data/reports", exist_ok=True)


def log(msg: str):
    """带时间戳的日志输出（跨平台安全）"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    # 安全打印：处理 Windows GBK 终端不兼容的 Unicode 字符
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(
            sys.stdout.encoding or 'utf-8', errors='replace'))
    with open("logs/daily.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def step1_collect_news(use_mock: bool, use_llm: bool) -> list:
    """Claw1: 采集科技新闻"""
    log("=" * 60)
    log("🦞 Claw1 - 开始新闻采集")
    log("=" * 60)

    from skills.tech_news_collector.collector import TechNewsCollector

    collector = TechNewsCollector(
        use_mock=use_mock,
        use_llm_filter=use_llm,
    )
    news_list = collector.collect()

    # 保存到文件
    output_path = "data/news.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    log(f"✅ Claw1 完成: 采集到 {len(news_list)} 条新闻，已保存至 {output_path}")
    return news_list


def step2_score_news(news_list: list, filtered: bool = False) -> list:
    """Claw2: 对新闻进行预测语句打分"""
    log("=" * 60)
    log("🦞 Claw2 - 开始新闻打分")
    log("=" * 60)

    from news_score import process_news, load_source_accuracy

    src_acc = load_source_accuracy()
    scored = []
    for item in news_list:
        title = item.get("title", "")
        content = item.get("content", "")
        source = item.get("source", "default")
        std_news = {"source": source, "title": title, "content": content}
        result = process_news(std_news, src_acc, filtered=filtered)
        scored.append(result)

    # 统计
    if scored:
        scores = [s.get("predictions_score", 0) for s in scored]
        avg_score = sum(scores) / len(scores)
        high = sum(1 for s in scores if s >= 0.6)
        mid = sum(1 for s in scores if 0.3 <= s < 0.6)
        low = sum(1 for s in scores if s < 0.3)
        log(f"✅ Claw2 完成: 平均分 {avg_score:.2f} | 高:{high} 中:{mid} 低:{low}")
    else:
        avg_score, high, mid, low = 0, 0, 0, 0
        log("⚠️ Claw2: 无新闻可打分")

    # 保存打分日志
    date_str = datetime.now().strftime("%Y-%m-%d")
    scored_file = f"data/reports/score_{date_str}_{datetime.now().strftime('%H%M%S')}.json"
    with open(scored_file, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2)
    log(f"   打分日志已保存: {scored_file}")

    return scored


def step3_generate_report(scored_news: list, stock_code: str = "600519") -> str:
    """Claw3: 生成每日分析简报"""
    log("=" * 60)
    log("🦞 Claw3 - 开始生成简报")
    log("=" * 60)

    from data_utils import get_all_data
    from agent_utils import (
        agent_market_analysis,
        agent_board_analysis,
        agent_stock_analysis,
        agent_summary,
    )

    # 获取行情数据
    all_data = get_all_data(stock_code=stock_code)
    index_data = all_data["大盘指数"]
    news_data = all_data["宏观新闻"]
    board_data = all_data["行业板块"]
    stock_data = all_data["个股行情"]
    finance_data = all_data["个股财报"]

    # 三大 Agent 分析
    log("   Agent1: 大盘分析...")
    res_market = agent_market_analysis(index_data, news_data)

    log("   Agent2: 板块分析...")
    res_board = agent_board_analysis(board_data)

    log("   Agent3: 个股分析...")
    res_stock = agent_stock_analysis(stock_data, finance_data)

    # 汇总
    log("   生成最终报告...")
    final_report = agent_summary(res_market, res_board, res_stock)

    # 附加评分摘要
    if scored_news:
        scores = [s.get("predictions_score", 0) for s in scored_news]
        avg = sum(scores) / len(scores)
        level = "高确定性" if avg >= 0.6 else ("中等确定性" if avg >= 0.3 else "低确定性/传闻居多")
        score_summary = f"\n\n---\n\n## 🦞 Claw2 新闻情绪评分摘要\n\n"
        score_summary += f"- 综合平均分: **{avg:.2f}** ({level})\n"
        score_summary += f"- 高确定性新闻: {sum(1 for s in scores if s >= 0.6)} 条\n"
        score_summary += f"- 中等确定性新闻: {sum(1 for s in scores if 0.3 <= s < 0.6)} 条\n"
        score_summary += f"- 低确定性/传闻: {sum(1 for s in scores if s < 0.3)} 条\n"
        final_report += score_summary

    log("✅ Claw3 完成: 报告已生成")
    return final_report


def save_report(report_text: str, news_list: list, date_str: str) -> str:
    """保存报告到 Markdown 文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"data/reports/report_{date_str}_{timestamp}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 🦞 每日科技股简报\n\n")
        f.write(f"**生成时间**: {datetime.now().isoformat()}\n\n")
        f.write(f"**新闻数量**: {len(news_list)} 条\n\n")
        f.write(f"---\n\n")
        f.write(f"## 📰 今日新闻列表\n\n")
        for i, item in enumerate(news_list, 1):
            f.write(f"{i}. **{item.get('title', '')}** ({item.get('source', '')})\n")
        f.write(f"\n---\n\n")
        f.write(report_text)
    log(f"📄 报告已保存: {filename}")
    return filename


def main():
    parser = argparse.ArgumentParser(
        description="Claw 数字员工 - 每日自动分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_daily.py                          # 完整运行
  python run_daily.py --mock                   # 模拟模式
  python run_daily.py --stock 000977           # 指定个股
  python run_daily.py --collect-only           # 仅采集新闻
  python run_daily.py --no-llm                 # 不使用 DeepSeek 筛选
        """,
    )
    parser.add_argument("--mock", action="store_true", help="使用模拟新闻数据（不访问网络）")
    parser.add_argument("--no-llm", action="store_true", help="不使用 DeepSeek 进行新闻筛选")
    parser.add_argument("--stock", default="600519", help="分析的个股代码（默认 600519）")
    parser.add_argument("--collect-only", action="store_true", help="仅采集新闻，不生成报告")
    parser.add_argument("--output-dir", default="data/reports", help="报告输出目录（默认 data/reports）")
    args = parser.parse_args()

    setup_logging()
    date_str = datetime.now().strftime("%Y-%m-%d")

    log("=" * 60)
    log(f"🚀 Claw 数字员工启动 - {date_str}")
    log(f"   模拟模式: {args.mock}")
    log(f"   LLM筛选: {not args.no_llm}")
    log(f"   个股代码: {args.stock}")
    log("=" * 60)

    try:
        # Step 1: 新闻采集
        news_list = step1_collect_news(use_mock=args.mock, use_llm=not args.no_llm)

        if args.collect_only:
            log("✅ 仅采集模式完成")
            return 0

        if not news_list:
            log("❌ 无新闻数据，无法继续分析")
            return 1

        # Step 2: 新闻打分
        news_filtered = args.mock or (not args.no_llm)
        scored_news = step2_score_news(news_list, filtered=news_filtered)

        # Step 3: 生成报告
        report = step3_generate_report(scored_news, stock_code=args.stock)

        # 保存报告
        saved_path = save_report(report, news_list, date_str)

        log("=" * 60)
        log(f"🎉 每日分析完成！")
        log(f"   新闻: {len(news_list)} 条")
        log(f"   报告: {saved_path}")
        log("=" * 60)

        return 0

    except Exception as e:
        log(f"❌ 运行失败: {e}")
        log(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
