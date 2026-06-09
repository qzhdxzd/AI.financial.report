#!/usr/bin/env python3
"""Claw 数字员工 - 每日科技股简报 Web 界面（集成大模型分析与筛选）"""

import json
import os
from datetime import datetime
import gradio as gr
import pandas as pd
import requests

# 导入采集模块
from skills.tech_news_collector.collector import TechNewsCollector

# 从环境变量读取 DeepSeek API Key
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def get_live_market_data():
    try:
        import akshare as ak
        # 使用 stock_zh_index_spot 获取实时指数
        df = ak.stock_zh_index_spot()
        sh = df[df['名称'] == '上证指数']
        sz = df[df['名称'] == '深证指数']
        sh_close = sh['最新价'].iloc[0] if not sh.empty else "--"
        sh_chg = sh['涨跌幅'].iloc[0] if not sh.empty else 0
        sz_close = sz['最新价'].iloc[0] if not sz.empty else "--"
        sz_chg = sz['涨跌幅'].iloc[0] if not sz.empty else 0
        return sh_close, sh_chg, sz_close, sz_chg
    except Exception as e:
        print(f"获取市场数据失败: {e}")
        return "--", 0, "--", 0
def call_deepseek(prompt: str, max_tokens: int = 1500) -> str:
    """调用 DeepSeek API，返回生成文本；若失败返回错误信息"""
    if not DEEPSEEK_API_KEY:
        return "⚠️ 未配置 DeepSeek API Key，请在环境变量中设置 DEEPSEEK_API_KEY"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            error = resp.json().get("error", {}).get("message", "未知错误")
            return f"⚠️ API 调用失败: {error}"
    except Exception as e:
        return f"⚠️ 请求异常: {e}"

def generate_ai_report(news_list):
    """使用 DeepSeek 生成每日简报"""
    if not news_list:
        return "今日无新闻数据，无法生成报告。"

    # 构建简洁的新闻摘要
    news_summary = []
    for item in news_list[:15]:
        title = item.get('title', '')
        content = item.get('content', '')[:200]
        news_summary.append(f"- {title}\n  {content}...")
    news_text = "\n".join(news_summary)

    prompt = f"""你是一位专业的股票分析师。请根据以下科技新闻，生成一份每日股市简报。

当前日期：{datetime.now().strftime("%Y-%m-%d")}

新闻列表：
{news_text}

请按以下格式输出：

### 一、市场情绪概览
（用一两句话总结整体市场情绪，乐观/谨慎/恐慌等）

### 二、热点板块分析
（列出受新闻影响的板块，如AI、半导体、新能源等，并说明利好/利空）

### 三、重点个股点评
（提及新闻中涉及的个股，分析短期影响）

### 四、今日操作建议
（给出明确的操作建议：关注哪些板块/个股，规避哪些风险）

注意：回答要简洁、专业，不要有多余的解释。"""
    
    report = call_deepseek(prompt, max_tokens=1500)
    return report

def refresh_market():
    """刷新市场数据，返回 DataFrame"""
    sh_close, sh_chg, sz_close, sz_chg = get_live_market_data()
    return pd.DataFrame([
        ["上证指数", sh_close, f"{sh_chg:.2f}%" if isinstance(sh_chg, (int, float)) else "--%"],
        ["深证指数", sz_close, f"{sz_chg:.2f}%" if isinstance(sz_chg, (int, float)) else "--%"]
    ], columns=["指数", "最新价", "涨跌幅"])

def run_daily_collection(use_mock: bool, use_llm: bool):
    """运行数据采集，返回新闻列表"""
    collector = TechNewsCollector(use_mock=use_mock, use_llm_filter=use_llm)
    news_list = collector.collect()
    # 保存到文件
    os.makedirs("data", exist_ok=True)
    output = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "total": len(news_list),
        "news": news_list
    }
    with open("data/news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return news_list

def collect_and_report(use_mock, use_llm):
    """采集新闻并生成报告"""
    news = run_daily_collection(use_mock, use_llm)
    if not news:
        return "❌ 未采集到任何新闻，请尝试使用模拟数据或检查网络。", f"采集完成，共 0 条新闻"
    report = generate_ai_report(news)
    return report, f"✅ 采集完成，共 {len(news)} 条新闻"

def create_ui():
    with gr.Blocks(title="Claw 数字员工 - 每日科技股简报", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🦞 Claw 数字员工 - 每日科技股简报系统")
        gr.Markdown("基于 OpenClaw 架构 | Claw1 数据采集 | Claw2 大模型分析 | Claw3 简报生成")
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📥 数据采集")
                use_mock = gr.Checkbox(label="使用模拟数据（演示模式）", value=True)
                use_llm = gr.Checkbox(label="使用大模型智能筛选（需 API Key）", value=False)
                collect_btn = gr.Button("🔄 采集今日数据", variant="primary")
                status_text = gr.Textbox(label="采集状态", lines=3, interactive=False)
            with gr.Column(scale=1):
                gr.Markdown("### 📊 市场概况")
                market_table = gr.Dataframe(
                    headers=["指数", "最新价", "涨跌幅"],
                    value=[["上证指数", "--", "--%"], ["深证指数", "--", "--%"]],
                    interactive=False
                )
                refresh_btn = gr.Button("🔄 刷新市场数据")
        
        gr.Markdown("### 📋 AI 智能简报")
        report_output = gr.Markdown("点击「采集今日数据」后生成简报")
        
        # 绑定事件
        collect_btn.click(
            collect_and_report,
            inputs=[use_mock, use_llm],
            outputs=[report_output, status_text]
        )
        refresh_btn.click(refresh_market, outputs=market_table)
    
    return demo

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)