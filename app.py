#!/usr/bin/env python3
"""Claw 数字员工 - 每日股票简报 Web 界面"""

import json
import os
from datetime import datetime

import gradio as gr
from dotenv import load_dotenv
import akshare as ak

# 导入自建模块
from skills.tech_news_collector.collector import TechNewsCollector

def run_collection():
    collector = TechNewsCollector(use_mock=False)  # 根据需要设置
    news = collector.collect()
    return news
from skills.market_analyzer.analyzer import MarketAnalyzer

load_dotenv()


def get_live_market_data():
    """获取实时大盘数据 - 适配新版akshare"""
    try:
        # 使用 stock_zh_a_spot 获取所有A股实时行情
        df = ak.stock_zh_a_spot()
        # 上证指数代码 sh000001
        sh_row = df[df['代码'] == 'sh000001']
        sz_row = df[df['代码'] == 'sz399001']
        
        sh_close = sh_row['最新价'].values[0] if not sh_row.empty else "--"
        sh_chg = sh_row['涨跌幅'].values[0] if not sh_row.empty else 0
        sz_close = sz_row['最新价'].values[0] if not sz_row.empty else "--"
        sz_chg = sz_row['涨跌幅'].values[0] if not sz_row.empty else 0
        return sh_close, sh_chg, sz_close, sz_chg
    except Exception as e:
        print(f"获取市场数据失败: {e}")
        # 回退到旧版接口尝试
        try:
            sh = ak.stock_zh_index_spot(symbol="sh000001")
            sz = ak.stock_zh_index_spot(symbol="sz399001")
            sh_close = sh['最新价'].iloc[0]
            sh_chg = sh['涨跌幅'].iloc[0]
            sz_close = sz['最新价'].iloc[0]
            sz_chg = sz['涨跌幅'].iloc[0]
            return sh_close, sh_chg, sz_close, sz_chg
        except:
            return "--", 0, "--", 0

def run_daily_collection():
    """运行每日数据采集"""
    collector = TechNewsCollector()
    news_list = collector.collect()
    
    output_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "total": len(news_list),
        "news": news_list
    }
    
    with open('data/news.json', 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    return output_data


def generate_brief_report():
    """生成简报"""
    # 获取最新数据
    try:
        with open('data/news.json', 'r', encoding='utf-8') as f:
            news_data = json.load(f)
    except FileNotFoundError:
        news_data = run_daily_collection()
    
    analyzer = MarketAnalyzer()
    analysis = analyzer.analyze(news_data)
    
    sh_close, sh_chg, sz_close, sz_chg = get_live_market_data()
    
    # 构建简报
    report = f"""# 📊 每日股票简报
生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 📈 市场概况
- **上证指数**: {sh_close} ({'+' if sh_chg >= 0 else ''}{sh_chg:.2f}%)
- **深证指数**: {sz_close} ({'+' if sz_chg >= 0 else ''}{sz_chg:.2f}%)

## 🗞️ 新闻摘要
共采集 **{analysis['total_news']}** 条科技新闻
- 事实性新闻占比：{sum(1 for n in news_data['news'] if n.get('is_fact', False))}/{analysis['total_news']}

## 💡 板块情绪
"""
    
    for sector, data in analysis['sector_scores'].items():
        sentiment_emoji = "🟢" if data['sentiment'] == "positive" else "🔴" if data['sentiment'] == "negative" else "🟡"
        report += f"- **{sector}**: {sentiment_emoji} 情绪: {data['sentiment']}, 评分: {data['score']:.2f}\n"
    
    # 大模型分析说明
    report += f"""
## 🤖 AI 分析说明
1. **事实性新闻**：包含具体数字（金额、百分比）、公告合同等的新闻，标记为 `is_fact=true`，权重更高
2. **预测类语句**：新闻中包含"预计、有望、可能、将"等关键词的句子，提取后计入情绪评分
3. **情绪评分**：基于新闻的事实性和预测语句强度综合计算，范围为 0~0.5（0表示中性，越高越积极）
4. **准确性验证**：用户可将后续实际涨跌幅与今日情绪评分对比，迭代优化模型

---
*免责声明：本简报仅供学习参考，不构成投资建议。*
"""
    
    return report


def create_ui():
    with gr.Blocks(title="Claw 数字员工 - 每日股票简报", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🦞 Claw 数字员工 - 每日科技股简报系统")
        gr.Markdown("基于 OpenClaw 架构的每日股票分析系统 - Claw1 数据采集 | Claw2 市场分析 | Claw3 简报生成")
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📥 数据采集")
                collect_btn = gr.Button("🔄 采集今日数据", variant="primary", size="lg")
                status_text = gr.Textbox(label="采集状态", lines=3)
            
            with gr.Column(scale=1):
                gr.Markdown("### 🤖 分析配置")
                model_choice = gr.Dropdown(
                    choices=["deepseek-chat", "glm-4.7-flash"],
                    label="AI 模型", value="deepseek-chat"
                )
                threshold_slider = gr.Slider(0, 1, value=0.5, label="情绪阈值", step=0.05)
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 📊 市场概况")
                market_table = gr.Dataframe(
                    headers=["指数", "最新价", "涨跌幅"],
                    value=[["上证指数", "--", "--%"], ["深证指数", "--", "--%"]],
                    interactive=False
                )
                refresh_btn = gr.Button("🔄 刷新市场数据")
            
            with gr.Column(scale=2):
                gr.Markdown("### 📋 每日简报")
                report_output = gr.Markdown()
        
        with gr.Row():
            gr.Markdown("### 📰 最新新闻列表")
            news_table = gr.Dataframe(
                headers=["时间", "标题", "来源", "事实性"],
                value=[], interactive=False
            )
        
        # 绑定事件
        collect_btn.click(
            lambda: run_daily_collection(),
            outputs=[status_text],
            api_name="collect"
        ).then(
            lambda: generate_brief_report(),
            outputs=[report_output]
        )
        
        refresh_btn.click(
            lambda: list(get_live_market_data()),
            outputs=None
        )
        
        # 加载初始数据
        demo.load(generate_brief_report, outputs=[report_output])
    
    return demo


if __name__ == "__main__":
    # 确保数据目录存在
    os.makedirs("data", exist_ok=True)
    
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)