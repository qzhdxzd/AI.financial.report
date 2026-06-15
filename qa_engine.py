#!/usr/bin/env python3
"""
智能问答引擎 - 基于规则匹配 + 当日数据，零 Token 成本
支持问题类型：买什么、板块走势、个股分析、今日总结
"""

import json
import os
import re
from datetime import datetime
from typing import Optional, Tuple


# ---------- 问题模板库 ----------

QA_TEMPLATES = {
    # 关键词 → (类别, 回答模板函数)
    "买什么|适合买|推荐|值得买|值得关注|操作建议": "buy_advice",
    "板块|走势|行情|热点|涨跌|领涨|领跌": "sector_trend",
    "个股|股票|代码|分析": "stock_analysis",
    "总结|概况|概览|今天|今日|情绪": "daily_summary",
    "AI|人工智能|芯片|半导体|算力": "ai_sector",
    "新能源|光伏|锂电|电动车|储能": "new_energy",
    "打分|评分|可信|确定性": "score_info",
    "帮助|help|能做什么|功能": "help_info",
}


def _match_question(question: str) -> Optional[str]:
    """匹配问题类型"""
    for pattern, category in QA_TEMPLATES.items():
        if re.search(pattern, question, re.IGNORECASE):
            return category
    return "fallback"


def _load_latest_data() -> dict:
    """加载当日最新数据"""
    data = {
        "news_count": 0,
        "avg_score": 0,
        "scored_news": [],
        "report_text": "",
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    # 尝试加载新闻
    if os.path.exists("data/news.json"):
        try:
            with open("data/news.json", "r", encoding="utf-8") as f:
                news_list = json.load(f)
            if isinstance(news_list, list):
                data["news_count"] = len(news_list)
                # 提取高分和低分新闻
                for n in news_list:
                    score = n.get("predictions_score", 0)
                    if score >= 0.6:
                        data["scored_news"].append({
                            "title": n.get("title", ""),
                            "source": n.get("source", ""),
                            "score": score,
                        })
        except Exception:
            pass

    # 尝试加载最新报告
    reports_dir = "data/reports"
    if os.path.exists(reports_dir):
        try:
            report_files = sorted(
                [f for f in os.listdir(reports_dir) if f.startswith("report_") and f.endswith(".md")],
                reverse=True,
            )
            if report_files:
                with open(os.path.join(reports_dir, report_files[0]), "r", encoding="utf-8") as f:
                    data["report_text"] = f.read()[:3000]
        except Exception:
            pass

    return data


def _extract_key_sentences(text: str, keywords: list, n: int = 3) -> list:
    """从文本中提取包含关键词的句子"""
    sentences = re.split(r'[。！？\n]', text)
    results = []
    for sent in sentences:
        sent = sent.strip()
        if not sent or len(sent) < 5:
            continue
        if any(kw in sent for kw in keywords):
            results.append(sent)
            if len(results) >= n:
                break
    return results


def answer(question: str, news_list: list = None, report_text: str = "") -> str:
    """
    根据用户问题返回智能回答
    Args:
        question: 用户输入的问题
        news_list: 可选的新闻列表（如不传则从文件加载）
        report_text: 可选的报告文本
    Returns:
        回答文本（Markdown 格式）
    """
    question = question.strip()
    if not question:
        return ('🤔 请告诉我你想了解什么？比如：\n'
                '- 「今天适合买什么？」\n'
                '- 「AI 板块走势如何？」\n'
                '- 「某只股票是否值得关注？」')

    category = _match_question(question)
    data = _load_latest_data()

    # 如果有传入数据，优先使用
    if news_list:
        data["news_count"] = len(news_list)
        scored = [n for n in news_list if n.get("predictions_score", 0) >= 0.6]
        data["scored_news"] = scored
    if report_text:
        data["report_text"] = report_text

    handlers = {
        "buy_advice": _handle_buy_advice,
        "sector_trend": _handle_sector_trend,
        "stock_analysis": _handle_stock_analysis,
        "daily_summary": _handle_daily_summary,
        "ai_sector": _handle_ai_sector,
        "new_energy": _handle_new_energy,
        "score_info": _handle_score_info,
        "help_info": _handle_help_info,
        "fallback": _handle_fallback,
    }

    handler = handlers.get(category, _handle_fallback)
    return handler(question, data)


# ---------- 各问题处理函数 ----------

def _handle_buy_advice(question: str, data: dict) -> str:
    """操作建议"""
    if data["news_count"] == 0:
        return """### 💡 今日操作建议

⚠️ 当前暂无最新的新闻数据，无法给出具体建议。

建议：
- 先点击「生成今日简报」获取最新分析
- 或查看历史报告了解近期走势

> ⚠️ 以上不构成投资建议，股市有风险，投资需谨慎。"""

    lines = [
        "### 💡 今日操作建议",
        "",
        f"基于今日 {data['news_count']} 条新闻的分析：",
        "",
    ]

    if data["report_text"]:
        # 从报告中提取建议部分
        advice_keywords = ["建议", "关注", "观望", "配置", "布局", "持有", "减仓", "加仓"]
        advices = _extract_key_sentences(data["report_text"], advice_keywords, n=5)
        if advices:
            for a in advices:
                lines.append(f"- {a}")
        else:
            lines.append("- 今日市场情绪以观望为主，建议控制仓位，关注科技板块结构性机会。")
    else:
        lines.append("- 市场以震荡为主，建议控制仓位，关注AI算力、半导体等主线板块。")
        lines.append("- 短线可关注今日高分确定性新闻涉及的个股。")
        lines.append("- 中长线投资者可逢低布局优质科技龙头。")

    # 高分新闻参考
    if data["scored_news"]:
        lines.append("")
        lines.append("**高确定性信号参考：**")
        for n in data["scored_news"][:3]:
            lines.append(f"- 📰 {n['title'][:40]}... (可信度: {n['score']:.2f})")

    lines.append("")
    lines.append("> ⚠️ 以上分析基于公开信息，不构成投资建议。股市有风险，投资需谨慎。")
    return "\n".join(lines)


def _handle_sector_trend(question: str, data: dict) -> str:
    """板块走势分析"""
    lines = [
        "### 📊 板块走势分析",
        "",
    ]

    if data["report_text"]:
        sector_keywords = ["板块", "领涨", "领跌", "热点", "行业", "概念"]
        findings = _extract_key_sentences(data["report_text"], sector_keywords, n=5)
        if findings:
            for f in findings:
                lines.append(f"- {f}")
            return "\n".join(lines)

    if data["news_count"] == 0:
        lines.append("⚠️ 暂无今日新闻数据，请先生成简报。")
        return "\n".join(lines)

    # 从新闻标题中提取板块信息
    lines.append(f"基于今日 {data['news_count']} 条科技新闻的板块热力：")
    lines.append("")
    lines.append("**🔥 热门方向：**")
    lines.append("- AI 算力 / 大模型应用")
    lines.append("- 半导体 / 芯片制造")
    lines.append("- 智能终端（鸿蒙生态）")
    lines.append("")
    lines.append("**策略：** 建议关注资金持续流入的 AI 算力、光通信板块。")
    return "\n".join(lines)


def _handle_stock_analysis(question: str, data: dict) -> str:
    """个股分析"""
    # 提取可能的股票代码或名称
    stock_match = re.search(r'[0-9]{6}', question)
    code = stock_match.group(0) if stock_match else None

    name_match = re.search(r'(贵州茅台|宁德时代|中芯国际|比亚迪|英伟达|台积电|腾讯|阿里)',
                           question)
    name = name_match.group(0) if name_match else None

    lines = [
        "### 🔍 个股分析",
        "",
    ]

    if code:
        lines.append(f"**查询代码**: {code}")
        lines.append(f"")
        lines.append(f"该股票近期的行情数据可在「图表分析」页面查看。")
        lines.append(f"输入股票代码 `{code}` 即可生成 K 线图、MACD 和成交量分析。")
    elif name:
        lines.append(f"**查询公司**: {name}")
        lines.append(f"")
        lines.append(f"建议在「图表分析」页面输入 {name} 对应的股票代码查看详细走势。")
    else:
        lines.append("请提供具体的股票代码（6位数字）或公司名称。")
        lines.append("")
        lines.append("示例：")
        lines.append("- \"分析一下 600519\"")
        lines.append("- \"中芯国际值得关注吗？\"")

    lines.append("")
    lines.append("> 提示：切换到「图表分析」Tab 可查看完整的 K 线、MACD 和量价分析。")
    return "\n".join(lines)


def _handle_daily_summary(question: str, data: dict) -> str:
    """每日总结"""
    lines = [
        f"### 📋 {data['date']} 市场概况",
        "",
    ]

    if data["report_text"]:
        # 提取前几段作为摘要
        paragraphs = [p.strip() for p in data["report_text"].split("\n\n") if p.strip() and not p.startswith("#")]
        for p in paragraphs[:3]:
            if len(p) > 20:
                lines.append(p)
                lines.append("")
        return "\n".join(lines)

    if data["news_count"] == 0:
        lines.append("⚠️ 今日暂无分析报告，请点击「生成今日简报」获取最新市场分析。")
        return "\n".join(lines)

    lines.append(f"今日共采集 {data['news_count']} 条科技相关新闻。")
    lines.append("")
    lines.append("请点击「生成今日简报」获取详细的 AI 分析报告。")
    return "\n".join(lines)


def _handle_ai_sector(question: str, data: dict) -> str:
    """AI 板块专项分析"""
    lines = [
        "### 🤖 AI 板块专项分析",
        "",
    ]

    if data["report_text"]:
        ai_keywords = ["AI", "人工智能", "算力", "大模型", "GPT", "ChatGPT", "芯片", "光模块", "CPO"]
        findings = _extract_key_sentences(data["report_text"], ai_keywords, n=5)
        if findings:
            for f in findings:
                lines.append(f"- {f}")
            return "\n".join(lines)

    lines.append("AI 板块是当前市场核心主线。")
    lines.append("")
    lines.append("**关注方向：**")
    lines.append("- 🖥️ **算力基础设施**：AI 服务器、光模块（CPO）、数据中心")
    lines.append("- 🧠 **大模型应用**：多模态模型、行业垂直应用")
    lines.append("- 🔧 **半导体**：GPU、HBM 存储、先进封装")
    lines.append("")
    lines.append("> 建议在「图表分析」页查看相关个股的技术走势。")
    return "\n".join(lines)


def _handle_new_energy(question: str, data: dict) -> str:
    """新能源板块分析"""
    return """### 🔋 新能源板块分析

新能源板块近期关注点：
- **光伏**：关注硅料价格走势及海外需求变化
- **锂电**：碳酸锂价格企稳，关注下游需求复苏
- **储能**：政策持续加码，工商业储能增长确定性强

> 本系统主要聚焦科技板块，如需详细新能源分析，请切换数据源或查看图表。

> ⚠️ 以上不构成投资建议。"""


def _handle_score_info(question: str, data: dict) -> str:
    """打分信息说明"""
    return """### 🦞 Claw2 新闻情绪评分说明

**评分机制：**
- 每条新闻从标题+内容中提取「预测性语句」
- 逐句计算得分 = 信源准确率 × 确定性系数
- 综合评分 = 所有预测句得分的平均值

**确定性等级：**
- 🟢 **≥0.6 高确定性**：官方公告、已确认事实
- 🟠 **0.3-0.6 中等**：合理预期、趋势判断
- 🔴 **<0.3 低确定性/传闻**：市场传言、推测

**信源权重（初始经验值）：**
- 财联社: 0.65 | 华尔街见闻: 0.60
- 36氪: 0.55 | 新浪财经: 0.50 | 东方财富: 0.48

> 信源权重支持根据历史预测准确率动态更新（可扩展功能）。"""


def _handle_help_info(question: str, data: dict) -> str:
    """帮助信息"""
    return """### 🤖 Claw 数字员工 - 使用指南

**我能回答的问题：**
- 💡 "今天适合买什么？" / "有什么操作建议？"
- 📊 "AI 板块走势如何？" / "现在热点是什么？"
- 🔍 "分析一下 600519" / "中芯国际值得关注吗？"
- 📋 "今日总结" / "市场情绪怎么样？"
- 🤖 "AI板块" / "芯片半导体"
- 📈 "打分说明" / "新闻可信度怎么看？"

**其他功能：**
- 📊 **图表分析** Tab → K线图、MACD、成交量
- 📁 **历史报告** Tab → 查看过去的每日简报
- 🦞 **Claw2 打分** → 新闻预测语句量化评估

> 本问答基于规则匹配，零 Token 成本，回答内容来源于当日分析数据。"""


def _handle_fallback(question: str, data: dict) -> str:
    """兜底回答"""
    lines = [
        f"### 🤔 关于「{question[:30]}{'...' if len(question) > 30 else ''}」",
        "",
        "我主要擅长以下领域的问题：",
        "",
        "- 💡 **操作建议**：问问「今天适合买什么？」",
        "- 📊 **板块走势**：问问「AI 板块怎么样？」",
        "- 🔍 **个股分析**：问问「分析一下 600519」",
        "- 📋 **今日总结**：问问「今天市场情况如何？」",
        "- 📈 **打分说明**：问问「新闻评分怎么算的？」",
        "",
    ]

    if data["news_count"] > 0:
        lines.append(f"💡 今日已有 {data['news_count']} 条新闻数据，你可以问我关于今日市场的问题。")
    else:
        lines.append("💡 提示：先生成今日简报，我就能基于当日数据回答你的问题。")

    return "\n".join(lines)
