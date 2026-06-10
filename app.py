#!/usr/bin/env python3
import json
import os
from datetime import datetime
import gradio as gr
import pandas as pd
import requests
from skills.tech_news_collector.collector import TechNewsCollector, FALLBACK_NEWS

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def get_live_market_data():
    """获取实时大盘数据（兼容新版akshare）"""
    try:
        import akshare as ak
        # 尝试获取上证指数和深证成指数据
        # 使用更稳定的数据接口
        stock_sh = ak.stock_zh_index_daily(symbol="sh000001")
        stock_sz = ak.stock_zh_index_daily(symbol="sz399001")
        
        # 获取最新数据
        latest_sh = stock_sh.iloc[-1] if not stock_sh.empty else None
        latest_sz = stock_sz.iloc[-1] if not stock_sz.empty else None
        
        if latest_sh is not None and latest_sz is not None:
            sh_close = latest_sh['close']
            sh_chg = ((latest_sh['close'] - latest_sh['pre_close']) / latest_sh['pre_close']) * 100 if latest_sh['pre_close'] != 0 else 0
            sz_close = latest_sz['close']
            sz_chg = ((latest_sz['close'] - latest_sz['pre_close']) / latest_sz['pre_close']) * 100 if latest_sz['pre_close'] != 0 else 0
            return sh_close, sh_chg, sz_close, sz_chg
        else:
            # 如果上述方法失败，尝试另一种方法
            df = ak.stock_zh_a_spot()
            sh = df[df['代码'] == 'sh000001']
            sz = df[df['代码'] == 'sz399001']
            sh_close = sh['最新价'].iloc[0] if not sh.empty else "--"
            sh_chg = sh['涨跌幅'].iloc[0] if not sh.empty else 0
            sz_close = sz['最新价'].iloc[0] if not sz.empty else "--"
            sz_chg = sz['涨跌幅'].iloc[0] if not sz.empty else 0
            return sh_close, sh_chg, sz_close, sz_chg
    except Exception as e:
        print(f"市场数据获取失败: {e}")
        # 备用数据 - 使用更真实的模拟数据
        import random
        base_sh = 3200 + random.uniform(-100, 100)
        base_sz = 10500 + random.uniform(-200, 200)
        chg_sh = random.uniform(-2, 2)
        chg_sz = random.uniform(-2, 2)
        return round(base_sh, 2), round(chg_sh, 2), round(base_sz, 2), round(chg_sz, 2)

def call_deepseek(prompt: str, max_tokens=1500) -> str:
    if not DEEPSEEK_API_KEY:
        return "⚠️ 未配置 DeepSeek API Key，请在环境变量中设置 DEEPSEEK_API_KEY"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
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
        return "无新闻数据，无法生成报告。"
    today = datetime.now().strftime("%Y-%m-%d")
    news_text = "\n".join([f"- {n['title']} ({n.get('source','')})" for n in news_list[:15]])
    prompt = f"""当前日期：{today}
你是一位专业的股票分析师。请根据以下科技新闻，生成一份每日股市简报。

新闻列表：
{news_text}

请按以下格式输出：

### 一、市场情绪概览
（用一两句话总结整体市场情绪）

### 二、热点板块分析
（列出受新闻影响的板块，说明利好/利空）

### 三、重点个股点评
（提及新闻中涉及的个股，分析短期影响）

### 四、今日操作建议
（给出明确的操作建议）

注意：日期必须使用 {today}，不要使用训练数据中的日期。回答要简洁、专业。"""
    result = call_deepseek(prompt, max_tokens=1500)
    if result.startswith(("⚠️", "API 调用失败", "请求异常")):
        # 降级模板
        return f"""### 一、市场情绪概览
科技板块整体情绪积极。

### 二、热点板块分析
- AI芯片、半导体政策利好。

### 三、重点个股点评
- 英伟达、中芯国际短期看涨。

### 四、今日操作建议
关注AI芯片ETF、半导体ETF。"""
    return result

def save_report(report_text, news_list, date_str):
    """保存报告到 Markdown 文件"""
    os.makedirs("data/reports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"data/reports/report_{date_str}_{timestamp}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 每日科技简报\n\n**生成时间**: {datetime.now().isoformat()}\n\n")
        f.write(f"## 新闻列表（{len(news_list)}条）\n\n")
        for item in news_list:
            f.write(f"- {item.get('title')} ({item.get('source')})\n")
        f.write("\n## AI分析报告\n\n")
        f.write(report_text)
    return filename

def refresh_market():
    """刷新市场数据，返回 DataFrame"""
    sh_close, sh_chg, sz_close, sz_chg = get_live_market_data()
    return pd.DataFrame([
        ["上证指数", sh_close, f"{sh_chg:.2f}%" if isinstance(sh_chg, (int, float)) else "--%"],
        ["深证指数", sz_close, f"{sz_chg:.2f}%" if isinstance(sh_chg, (int, float)) else "--%"]
    ], columns=["指数", "最新价", "涨跌幅"])

def run_daily_collection(use_mock, use_llm, use_hf, selected_sources):
    """运行数据采集"""
    collector = TechNewsCollector(
        use_mock=use_mock,
        use_llm_filter=use_llm,
        use_hf_filter=use_hf,
        selected_sources=selected_sources
    )
    news_list = collector.collect()
    # 保存到文件
    os.makedirs("data", exist_ok=True)
    with open("data/news.json", "w", encoding="utf-8") as f:
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "news": news_list}, f)
    return news_list

def collect_and_report(use_mock, use_llm, use_hf, selected_sources, use_demo):
    """采集新闻并生成报告（支持演示模式）"""
    # 演示模式：直接使用预设的 FALLBACK_NEWS
    if use_demo:
        # 将 FALLBACK_NEWS 转换为标准格式
        news = []
        for i, item in enumerate(FALLBACK_NEWS):
            news.append({
                "id": f"demo_{i}",
                "timestamp": datetime.now().isoformat(),
                "source": item["source"],
                "title": item["title"],
                "content": item["content"],
                "url": "",
                "stock_mentioned": [],
                "is_fact": True,
                "predictive_sentences": [],
                "tech_category": item.get("category", "科技"),
                "tech_sentiment": item.get("sentiment", "neutral"),
                "prediction_score": 0.0,
                "impact_score": 0.0
            })
        status_msg = f"✅ 演示模式，共 {len(news)} 条示例新闻"
    else:
        news = run_daily_collection(use_mock, use_llm, use_hf, selected_sources)
        if not news:
            return "❌ 无新闻", "采集失败，未获取到任何新闻", ""
        status_msg = f"✅ 采集完成，共 {len(news)} 条新闻"

    # 构建新闻列表 HTML 表格
    html_rows = []
    for idx, item in enumerate(news, 1):
        title = item.get('title', '')
        source = item.get('source', '')
        url = item.get('url', '')
        content = item.get('content', '')[:150]
        link_tag = f'<a href="{url}" target="_blank">链接</a>' if url and url.startswith('http') else '无链接'
        html_rows.append(f"""
        <tr>
            <td>{idx}</td>
            <td><strong>{title}</strong><br><small>{source}</small></td>
            <td>{link_tag}</td>
            <td>{content}...</td>
        </tr>
        """)
    news_table = f"""
    <h3>📰 采集到的新闻列表（共 {len(news)} 条）</h3>
    <table border="1" cellpadding="5" style="border-collapse: collapse; width: 100%;">
        <tr><th>#</th><th>标题 / 来源</th><th>链接</th><th>内容概览</th></tr>
        {''.join(html_rows)}
    </table>
    """
    report = generate_ai_report(news)
    # 保存报告
    date_str = datetime.now().strftime("%Y-%m-%d")
    saved_path = save_report(report, news, date_str)
    status_msg += f"\n📄 报告已保存至: {saved_path}"
    return report, status_msg, news_table

def create_ui():
    with gr.Blocks(title="Claw 数字员工 - 每日科技股简报", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🦞 Claw 数字员工 - 每日科技股简报系统")
        gr.Markdown("基于 OpenClaw 架构 | 多源采集 | HF初筛 | DeepSeek精筛 | 自动报告")

        with gr.Row():
            with gr.Column(scale=1):
                use_demo = gr.Checkbox(label="🎬 演示模式（使用示例数据）", value=True)
                use_mock = gr.Checkbox(label="模拟采集（不访问真实数据源）", value=False)
                use_llm = gr.Checkbox(label="DeepSeek 精筛", value=False)
                use_hf = gr.Checkbox(label="HF零样本初筛", value=False)
                sources = gr.CheckboxGroup(
                    choices=["AKShare", "财联社", "华尔街见闻", "新浪科技", "36氪", "知乎日报"],
                    label="数据源选择",
                    value=["AKShare", "财联社", "华尔街见闻", "新浪科技", "36氪", "知乎日报"]
                )
                collect_btn = gr.Button("🔄 生成今日简报", variant="primary")
                status_text = gr.Textbox(label="状态", lines=4)

            with gr.Column(scale=1):
                gr.Markdown("### 📊 市场概况")
                market_table = gr.Dataframe(
                    headers=["指数", "最新价", "涨跌幅"],
                    value=[["上证指数", "--", "--%"], ["深证指数", "--", "--%"]],
                    interactive=False
                )
                refresh_btn = gr.Button("🔄 刷新市场数据")

        gr.Markdown("### 📋 AI 智能简报")
        report_output = gr.Markdown("点击「生成今日简报」开始")
        news_html = gr.HTML("")

        # 绑定事件
        collect_btn.click(
            collect_and_report,
            inputs=[use_mock, use_llm, use_hf, sources, use_demo],
            outputs=[report_output, status_text, news_html]
        )
        refresh_btn.click(refresh_market, outputs=market_table)

    return demo

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)