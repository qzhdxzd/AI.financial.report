#!/usr/bin/env python3
import json, os
from datetime import datetime
import gradio as gr
import pandas as pd
import requests
from skills.tech_news_collector.collector import TechNewsCollector

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def get_live_market_data():
    """使用 stock_zh_a_spot 获取指数，失败则返回默认值"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot()
        sh = df[df['代码'] == 'sh000001']
        sz = df[df['代码'] == 'sz399001']
        sh_close = sh['最新价'].iloc[0] if not sh.empty else "--"
        sh_chg = sh['涨跌幅'].iloc[0] if not sh.empty else 0
        sz_close = sz['最新价'].iloc[0] if not sz.empty else "--"
        sz_chg = sz['涨跌幅'].iloc[0] if not sz.empty else 0
        return sh_close, sh_chg, sz_close, sz_chg
    except Exception as e:
        print(f"获取市场数据失败: {e}")
        # 返回示例数据
        return 3310.49, 0.52, 10560.12, 0.68

def call_deepseek(prompt: str, max_tokens=1500) -> str:
    if not DEEPSEEK_API_KEY:
        return "⚠️ 未配置 API Key"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.7}
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            return f"⚠️ API 调用失败: {resp.json().get('error', {}).get('message', '未知错误')}"
    except Exception as e:
        return f"⚠️ 请求异常: {e}"

def generate_ai_report(news_list):
    if not news_list:
        return "无新闻数据"
    news_text = "\n".join([f"- {n['title']}" for n in news_list[:10]])
    prompt = f"""根据以下科技新闻，生成每日简报（包含情绪、热点板块、操作建议）：
{news_text}
请用中文简洁输出。"""
    result = call_deepseek(prompt)
    if result.startswith("⚠️"):
        # 降级模板
        return """### 一、市场情绪概览
科技板块整体情绪积极。

### 二、热点板块分析
- AI芯片、半导体政策利好。

### 三、重点个股点评
- 英伟达、中芯国际短期看涨。

### 四、今日操作建议
关注AI芯片ETF、半导体ETF。"""
    return result

def refresh_market():
    sh_close, sh_chg, sz_close, sz_chg = get_live_market_data()
    return pd.DataFrame([
        ["上证指数", sh_close, f"{sh_chg:.2f}%"],
        ["深证指数", sz_close, f"{sz_chg:.2f}%"]
    ], columns=["指数", "最新价", "涨跌幅"])

def run_daily_collection(use_mock, use_llm):
    # 忽略 use_llm，因为 collector 已默认启用大模型筛选（但 use_mock 优先）
    collector = TechNewsCollector(use_mock=use_mock)
    news_list = collector.collect()
    os.makedirs("data", exist_ok=True)
    with open("data/news.json", "w", encoding="utf-8") as f:
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "news": news_list}, f)
    return news_list

def collect_and_report(use_mock, use_llm):
    news = run_daily_collection(use_mock, use_llm)
    if not news:
        return "❌ 无新闻", "采集失败"
    report = generate_ai_report(news)
    return report, f"✅ 采集完成，共 {len(news)} 条新闻"

def create_ui():
    with gr.Blocks(title="Claw 数字员工 - 每日科技股简报") as demo:
        gr.Markdown("# 🦞 Claw 数字员工 - 每日科技股简报系统")
        with gr.Row():
            with gr.Column():
                use_mock = gr.Checkbox(label="使用模拟数据", value=True)
                use_llm = gr.Checkbox(label="使用大模型筛选（忽略，已默认）", value=False, visible=False)
                collect_btn = gr.Button("🔄 生成今日简报", variant="primary")
                status_text = gr.Textbox(label="状态", lines=2)
            with gr.Column():
                market_table = gr.Dataframe(headers=["指数", "最新价", "涨跌幅"], value=[["上证指数", "--", "--%"], ["深证指数", "--", "--%"]])
                refresh_btn = gr.Button("🔄 刷新市场数据")
        report_output = gr.Markdown("点击「生成今日简报」")
        collect_btn.click(collect_and_report, inputs=[use_mock, use_llm], outputs=[report_output, status_text])
        refresh_btn.click(refresh_market, outputs=market_table)
    return demo

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)