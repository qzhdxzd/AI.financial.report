#!/usr/bin/env python3
from agent_utils import agent_market_analysis, agent_board_analysis, agent_stock_analysis, agent_summary, llm_chat
from skills.score_skill import score_finance_report
from data_utils import get_all_data
import json
import os
import sys
from datetime import datetime
import gradio as gr
import pandas as pd
from skills.tech_news_collector.collector import TechNewsCollector, FALLBACK_NEWS
# 导入Claw2 新闻打分相关函数
from news_score import process_news, load_source_accuracy
from data_utils import get_macro_news
from chart_utils import plot_kline, plot_macd, plot_volume_analysis, plot_index_overview
from qa_engine import answer as qa_answer


# ---------- 跨平台安全打印（Windows GBK / Linux UTF-8 兼容）----------
def safe_print(*args, **kwargs):
    """安全打印，自动处理终端编码不兼容字符"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = ' '.join(str(a) for a in args)
        print(text.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(
            sys.stdout.encoding or 'utf-8', errors='replace'), **kwargs)


def get_live_market_data():
    """获取实时大盘数据（多级回退，确保数据真实）"""
    import akshare as ak

    # ---- 方案1：stock_zh_index_spot_em（最新版akshare推荐，实时行情）----
    try:
        df_spot = ak.stock_zh_index_spot_em()
        # 精确匹配指数名称（避免 contains 匹配到 上证信息/上证材料 等）
        sh_row = df_spot[df_spot['名称'].isin(['上证指数', '上证综指'])]
        sz_row = df_spot[df_spot['名称'] == '深证成指']
        # 如果深证成指名称匹配不到，尝试用代码匹配
        if sz_row.empty:
            sz_row = df_spot[df_spot['代码'].isin(['399001', 'sz399001'])]
        if not sh_row.empty and not sz_row.empty:
            sh_close = float(sh_row['最新价'].iloc[0])
            sh_chg = float(sh_row['涨跌幅'].iloc[0])
            sz_close = float(sz_row['最新价'].iloc[0])
            sz_chg = float(sz_row['涨跌幅'].iloc[0])
            safe_print(f"[market] spot_em OK: SH={sh_close}({sh_chg:+.2f}%) SZ={sz_close}({sz_chg:+.2f}%)")
            return sh_close, sh_chg, sz_close, sz_chg
    except Exception as e1:
        safe_print(f"[market] spot_em fail: {e1}")

    # ---- 方案2：stock_zh_index_daily（历史日线）----
    for sh_sym, sz_sym in [("sh000001", "sz399001"), ("000001", "399001")]:
        try:
            stock_sh = ak.stock_zh_index_daily(symbol=sh_sym)
            stock_sz = ak.stock_zh_index_daily(symbol=sz_sym)
            if (stock_sh is not None and not stock_sh.empty and
                    stock_sz is not None and not stock_sz.empty):
                latest_sh = stock_sh.iloc[-1]
                latest_sz = stock_sz.iloc[-1]
                sh_close = latest_sh['close']
                pre_sh = latest_sh.get('pre_close', latest_sh.get('open', latest_sh['close']))
                sh_chg = ((sh_close - pre_sh) / pre_sh) * 100 if pre_sh != 0 else 0
                sz_close = latest_sz['close']
                pre_sz = latest_sz.get('pre_close', latest_sz.get('open', latest_sz['close']))
                sz_chg = ((sz_close - pre_sz) / pre_sz) * 100 if pre_sz != 0 else 0
                safe_print(f"[market] index_daily OK: SH={sh_close}({sh_chg:+.2f}%) SZ={sz_close}({sz_chg:+.2f}%)")
                return sh_close, sh_chg, sz_close, sz_chg
        except Exception:
            continue

    # ---- 方案3：stock_zh_a_spot（全A股实时行情）----
    try:
        df = ak.stock_zh_a_spot()
        for sh_code, sz_code in [('sh000001', 'sz399001'), ('000001', '399001')]:
            sh = df[df['代码'] == sh_code]
            sz = df[df['代码'] == sz_code]
            if not sh.empty and not sz.empty:
                sh_close = sh['最新价'].iloc[0]
                sh_chg = sh['涨跌幅'].iloc[0]
                sz_close = sz['最新价'].iloc[0]
                sz_chg = sz['涨跌幅'].iloc[0]
                safe_print(f"[market] zh_a_spot OK: SH={sh_close}({sh_chg:+.2f}%) SZ={sz_close}({sz_chg:+.2f}%)")
                return sh_close, sh_chg, sz_close, sz_chg
    except Exception as e3:
        safe_print(f"[market] zh_a_spot fail: {e3}")

    # ---- 全部失败：返回错误标识，绝不编造数据 ----
    safe_print("[market] All sources failed - check network or akshare version")
    return None, None, None, None


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
    result = llm_chat(prompt, max_tokens=1500)
    if result.startswith(("API", "Request", "未配置")):
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
        f.write(f"# Claw 每日科技简报\n\n**生成时间**: {datetime.now().isoformat()}\n\n")
        f.write(f"## 新闻列表（{len(news_list)}条）\n\n")
        for item in news_list:
            f.write(f"- {item.get('title')} ({item.get('source')})\n")
        f.write("\n## AI分析报告\n\n")
        f.write(report_text)
    return filename


def run_full_analysis():
    """一键执行：数据获取 -> 三大Agent分析 -> 生成最终报告"""
    # 1. 获取全部数据
    all_data = get_all_data()
    index_data = all_data["大盘指数"]
    news_data = all_data["宏观新闻"]
    board_data = all_data["行业板块"]
    stock_data = all_data["个股行情"]
    finance_data = all_data["个股财报"]

    # 2. 调用三位成员对应的分析函数
    res_market = agent_market_analysis(index_data, news_data)
    res_board = agent_board_analysis(board_data)
    res_stock = agent_stock_analysis(stock_data, finance_data)

    # 3. 汇总成最终报告
    final_report = agent_summary(res_market, res_board, res_stock)

    # 4. 自动保存到历史记录
    date_str = datetime.now().strftime("%Y-%m-%d")
    news_list = [{"title": news_data, "source": "宏观新闻汇总"}]
    save_report(final_report, news_list, date_str)

    return final_report


def score_news_list(news_list, filtered=False):
    """对新闻列表进行Claw2打分，返回打分后的列表和汇总统计"""
    src_acc = load_source_accuracy()
    scored = []
    for item in news_list:
        title = item.get("title", "")
        content = item.get("content", "")
        source = item.get("source", "default")
        std_news = {"source": source, "title": title, "content": content}
        result = process_news(std_news, src_acc, filtered=filtered)
        scored.append(result)

    if scored:
        scores = [s.get("predictions_score", 0) for s in scored]
        avg_score = sum(scores) / len(scores)
        high = sum(1 for s in scores if s >= 0.6)
        mid = sum(1 for s in scores if 0.3 <= s < 0.6)
        low = sum(1 for s in scores if s < 0.3)
    else:
        avg_score, high, mid, low = 0, 0, 0, 0

    return scored, {"avg_score": avg_score, "high": high, "mid": mid, "low": low, "total": len(scored)}


def score_to_color(score):
    """分数转颜色"""
    if score >= 0.7:
        return "#27ae60"
    elif score >= 0.4:
        return "#f39c12"
    else:
        return "#e74c3c"


def render_score_bar(score, max_width=100):
    """渲染分数条"""
    color = score_to_color(score)
    pct = min(score, 1.0)
    width = int(pct * max_width)
    return f'<span style="display:inline-block;width:{width}px;height:12px;background:{color};border-radius:3px;"></span>'


def score_news_to_html(news_list, filtered=False):
    """将新闻打分结果格式化为可视化HTML"""
    scored_list, stats = score_news_list(news_list, filtered=filtered)

    if not scored_list:
        return "<p>无新闻数据可供打分。</p>", "无新闻数据"

    # 顶部汇总卡片
    avg = stats["avg_score"]
    avg_color = score_to_color(avg)
    level = "高确定性" if avg >= 0.6 else ("中等确定性" if avg >= 0.3 else "低确定性/传闻居多")

    summary_html = f"""
    <div style="background:#1e1e2e; border-radius:12px; padding:16px 20px; margin-bottom:16px; color:#cdd6f4;">
        <h3 style="margin:0 0 12px 0; color:#f5c2e7;">Claw2 新闻情绪评分</h3>
        <div style="display:flex; gap:20px; flex-wrap:wrap; align-items:center;">
            <div style="text-align:center;">
                <div style="font-size:36px; font-weight:bold; color:{avg_color};">{avg:.2f}</div>
                <div style="font-size:12px; color:#a6adc8;">综合平均分</div>
                <div style="font-size:13px; color:{avg_color};">{level}</div>
            </div>
            <div style="flex:1; min-width:200px;">
                <div style="margin:4px 0;"><span style="color:#27ae60;">HIGH</span> 高确定性 (>=0.6): <b>{stats['high']}</b> 条</div>
                <div style="margin:4px 0;"><span style="color:#f39c12;">MID</span> 中等确定性 (0.3-0.6): <b>{stats['mid']}</b> 条</div>
                <div style="margin:4px 0;"><span style="color:#e74c3c;">LOW</span> 低确定性/传闻 (<0.3): <b>{stats['low']}</b> 条</div>
                <div style="margin:4px 0; color:#a6adc8;">总计: {stats['total']} 条新闻</div>
            </div>
        </div>
    </div>
    """

    # 详细表格
    rows = []
    for i, item in enumerate(scored_list, 1):
        score = item.get("predictions_score", 0)
        color = score_to_color(score)
        preds = item.get("scored_predictions", [])
        source = item.get("source", "")
        title = item.get("title", "")

        pred_details = ""
        if preds:
            pred_items = []
            for p in preds[:3]:
                ps = p.get("score", 0)
                pt = p.get("text", "")[:60]
                pc = score_to_color(ps)
                pred_items.append(f'<span style="color:{pc};">[{ps:.2f}]</span> {pt}')
            pred_details = "<br>".join(pred_items)
        else:
            pred_details = "<span style='color:#6c7086;'>无预测性语句</span>"

        rows.append(f"""
        <tr style="border-bottom:1px solid #313244;">
            <td style="padding:8px; vertical-align:top;">{i}</td>
            <td style="padding:8px; vertical-align:top;">
                <b>{title[:50]}</b>
                <br><small style="color:#a6adc8;">{source}</small>
            </td>
            <td style="padding:8px; font-size:13px; vertical-align:top;">{pred_details}</td>
            <td style="padding:8px; text-align:center; vertical-align:top;">
                <span style="font-size:18px; font-weight:bold; color:{color};">{score:.2f}</span>
                <br>{render_score_bar(score, 80)}
            </td>
        </tr>
        """)

    table_html = f"""
    <div style="background:#1e1e2e; border-radius:12px; padding:16px 20px; color:#cdd6f4;">
        <h4 style="margin:0 0 12px 0;">Score List</h4>
        <table style="width:100%; border-collapse:collapse;">
            <tr style="background:#313244;">
                <th style="padding:8px; text-align:left;">#</th>
                <th style="padding:8px; text-align:left;">Title / Source</th>
                <th style="padding:8px; text-align:left;">Predictions & Scores</th>
                <th style="padding:8px; text-align:center;">Score</th>
            </tr>
            {''.join(rows)}
        </table>
    </div>
    """

    full_html = summary_html + table_html
    status_line = f"Score {avg:.2f} | High:{stats['high']} Mid:{stats['mid']} Low:{stats['low']}"
    return full_html, status_line


def get_news_with_score():
    """Claw2打分按钮回调：采集新闻 -> 打分 -> 返回可视化HTML"""
    try:
        news_df = get_macro_news()
        if hasattr(news_df, "to_dict"):
            news_list = news_df.to_dict("records")
        else:
            news_list = news_df

        if not news_list:
            return "<p>No news data.</p>"

        html, _ = score_news_to_html(news_list)
        return html
    except Exception as err:
        return f"<p style='color:red;'>Score failed: {str(err)}</p>"


def refresh_market():
    """刷新市场数据，返回 DataFrame"""
    sh_close, sh_chg, sz_close, sz_chg = get_live_market_data()

    def fmt_val(val):
        """安全格式化数值"""
        if val is None:
            return "获取失败"
        if isinstance(val, (int, float)):
            return round(val, 2)
        return str(val)

    def fmt_chg(val):
        """安全格式化涨跌幅"""
        if val is None:
            return "--"
        if isinstance(val, (int, float)):
            return f"{val:+.2f}%"
        return str(val)

    return pd.DataFrame([
        ["上证指数", fmt_val(sh_close), fmt_chg(sh_chg)],
        ["深证指数", fmt_val(sz_close), fmt_chg(sz_chg)]
    ], columns=["指数", "最新价", "涨跌幅"])


def run_daily_collection(use_mock, use_llm, selected_sources):
    """运行数据采集"""
    collector = TechNewsCollector(
        use_mock=use_mock,
        use_llm_filter=use_llm,
        selected_sources=selected_sources
    )
    news_list = collector.collect()
    os.makedirs("data", exist_ok=True)
    with open("data/news.json", "w", encoding="utf-8") as f:
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "news": news_list}, f)
    return news_list


def collect_and_report(use_mock, use_llm, selected_sources, use_demo):
    """采集新闻并生成报告（支持演示模式）"""
    if use_demo:
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
        status_msg = f"OK: demo mode, {len(news)} sample news"
    else:
        news = run_daily_collection(use_mock, use_llm, selected_sources)
        if not news:
            return "No news", "Collection failed", "", "<p style='color:red;'>No news data for scoring</p>"
        status_msg = f"OK: collected {len(news)} news items"

    # 构建新闻列表 HTML
    html_rows = []
    for idx, item in enumerate(news, 1):
        title = item.get('title', '')
        source = item.get('source', '')
        url = item.get('url', '')
        content = item.get('content', '')[:150]
        link_tag = f'<a href="{url}" target="_blank">link</a>' if url and url.startswith('http') else 'no link'
        html_rows.append(f"""
        <tr>
            <td>{idx}</td>
            <td><strong>{title}</strong><br><small>{source}</small></td>
            <td>{link_tag}</td>
            <td>{content}...</td>
        </tr>
        """)
    news_table = f"""
    <h3>News List ({len(news)} items)</h3>
    <table border="1" cellpadding="5" style="border-collapse: collapse; width: 100%;">
        <tr><th>#</th><th>Title / Source</th><th>Link</th><th>Content</th></tr>
        {''.join(html_rows)}
    </table>
    """
    report = generate_ai_report(news)
    # Claw2 打分
    news_filtered = use_demo or use_llm
    score_html, score_status = score_news_to_html(news, filtered=news_filtered)
    # 保存报告
    date_str = datetime.now().strftime("%Y-%m-%d")
    saved_path = save_report(report, news, date_str)
    # 保存打分日志
    scored_file = f"data/reports/score_{date_str}_{datetime.now().strftime('%H%M%S')}.json"
    scored_list, _ = score_news_list(news, filtered=news_filtered)
    with open(scored_file, "w", encoding="utf-8") as f:
        json.dump(scored_list, f, ensure_ascii=False, indent=2)
    status_msg += f"\nReport saved: {saved_path}"
    status_msg += f"\nScore log: {scored_file}"
    status_msg += f"\n{score_status}"
    return report, status_msg, news_table, score_html


def run_full_analysis_with_score():
    """运行全部分析 + 评分"""
    try:
        final_report = run_full_analysis()
        score_result = score_finance_report(final_report)
        combined = final_report + "\n\n---\n\n" + score_result
        status = "OK: Full analysis done"
        return combined, status
    except Exception as e:
        return f"Analysis failed: {str(e)}", f"Error: {str(e)}"


# ========== 图表分析 Tab 回调 ==========

def update_chart(stock_code: str, days: int, chart_type: str):
    """根据股票代码和图表类型生成 Plotly 图表"""
    if not stock_code or not stock_code.strip():
        stock_code = "600519"

    stock_code = stock_code.strip()
    name_map = {
        "600519": "贵州茅台", "000977": "浪潮信息", "002230": "科大讯飞",
        "300750": "宁德时代", "688981": "中芯国际", "002594": "比亚迪",
    }
    stock_name = name_map.get(stock_code, stock_code)

    chart_map = {
        "K线图+均线+成交量": lambda: plot_kline(stock_code, days=days, stock_name=stock_name),
        "Kline+MA+Volume": lambda: plot_kline(stock_code, days=days, stock_name=stock_name),
        "K线图 + 均线 + 成交量": lambda: plot_kline(stock_code, days=days, stock_name=stock_name),
        "MACD 指标": lambda: plot_macd(stock_code, days=days, stock_name=stock_name),
        "MACD": lambda: plot_macd(stock_code, days=days, stock_name=stock_name),
        "量价分析": lambda: plot_volume_analysis(stock_code, days=days, stock_name=stock_name),
        "Volume Analysis": lambda: plot_volume_analysis(stock_code, days=days, stock_name=stock_name),
        "大盘指数对比": lambda: plot_index_overview(),
        "Index Comparison": lambda: plot_index_overview(),
    }
    factory = chart_map.get(chart_type, chart_map["Kline+MA+Volume"])
    fig = factory()

    return fig


# ========== 智能问答 Tab 回调 ==========

def chat_qa(message: str, history: list):
    """处理用户问答消息（兼容 Gradio messages 格式）"""
    if not message or not message.strip():
        return "", history

    news_list = []
    try:
        if os.path.exists("data/news.json"):
            with open("data/news.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and 'news' in data:
                news_list = data['news']
            elif isinstance(data, list):
                news_list = data
    except Exception:
        pass

    answer_text = qa_answer(message, news_list=news_list)

    if history is None:
        history = []
    # Gradio messages 格式: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": answer_text})
    return "", history


def clear_chat():
    """清空对话历史"""
    return [], None


# ========== 历史报告 Tab 回调 ==========

def list_history_reports():
    """列出所有历史报告文件"""
    reports_dir = "data/reports"
    if not os.path.exists(reports_dir):
        return "No historical reports yet", gr.Dropdown(choices=[])

    report_files = sorted(
        [f for f in os.listdir(reports_dir) if f.startswith("report_") and f.endswith(".md")],
        reverse=True
    )

    if not report_files:
        return "No historical reports yet", gr.Dropdown(choices=[])

    preview_lines = [f"### {len(report_files)} historical reports\n"]
    for i, fname in enumerate(report_files[:20], 1):
        parts = fname.replace(".md", "").split("_")
        date_str = parts[1] if len(parts) > 1 else "unknown"
        preview_lines.append(f"{i}. **{date_str}** -- `{fname}`")

    preview = "\n".join(preview_lines)
    choices = report_files
    return preview, gr.Dropdown(choices=choices, value=choices[0] if choices else None)


def view_history_report(selected_file: str):
    """查看选中的历史报告内容"""
    if not selected_file:
        return "Select a report from dropdown", ""

    filepath = os.path.join("data/reports", selected_file)
    if not os.path.exists(filepath):
        return f"File not found: {selected_file}", ""

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    return content, selected_file


def create_ui():
    with gr.Blocks(title="Claw 数字员工 - 每日科技股简报", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🦞 Claw 数字员工 - 每日科技股简报系统")
        gr.Markdown("基于 OpenClaw 架构 | 多源采集 | DeepSeek精筛 | 自动报告 | 零Token成本")

        # ==============================
        # Tab 1: 每日简报
        # ==============================
        with gr.Tab("📊 每日简报"):
            with gr.Row():
                with gr.Column(scale=1):
                    use_demo = gr.Checkbox(label="🎬 演示模式（使用示例数据）", value=True)
                    use_mock = gr.Checkbox(label="模拟采集（不访问真实数据源）", value=False)
                    use_llm = gr.Checkbox(label="DeepSeek 精筛", value=False)
                    sources = gr.CheckboxGroup(
                        choices=["AKShare", "新浪财经", "华尔街见闻", "财联社", "36氪", "东方财富"],
                        label="数据源选择",
                        value=["AKShare", "新浪财经", "华尔街见闻", "财联社"]
                    )
                    collect_btn = gr.Button("🔄 生成今日简报", variant="primary")
                    full_analysis_btn = gr.Button("📈 三大Agent全部分析 + 评分", variant="secondary")
                    score_news_btn = gr.Button("📊 Claw2 新闻独立打分", variant="secondary")
                    status_text = gr.Textbox(label="运行状态", lines=5)

                with gr.Column(scale=1):
                    gr.Markdown("### 📊 市场概况")
                    market_table = gr.Dataframe(
                        headers=["指数", "最新价", "涨跌幅"],
                        value=[["上证指数", "--", "--%"], ["深证指数", "--", "--%"]],
                        interactive=False
                    )
                    refresh_btn = gr.Button("🔄 刷新市场数据")

            gr.Markdown("### 📋 AI 智能简报")
            report_output = gr.Markdown("点击「生成今日简报」开始分析")
            news_html = gr.HTML("")

            gr.Markdown("---")
            gr.Markdown("### 🦞 Claw2 新闻情绪评分")
            score_html = gr.HTML("<p style='color:#888;'>点击上方按钮进行新闻采集与打分</p>")

            collect_btn.click(
                collect_and_report,
                inputs=[use_mock, use_llm, sources, use_demo],
                outputs=[report_output, status_text, news_html, score_html]
            )
            full_analysis_btn.click(
                run_full_analysis_with_score,
                outputs=[report_output, status_text]
            )
            score_news_btn.click(
                get_news_with_score,
                outputs=score_html
            )
            refresh_btn.click(refresh_market, outputs=market_table)

        # ==============================
        # Tab 2: 图表分析
        # ==============================
        with gr.Tab("📈 图表分析"):
            gr.Markdown("### 📈 交互式技术图表（Plotly）")
            gr.Markdown("输入股票代码，选择图表类型和时间范围，即可生成交互式技术分析图。")

            with gr.Row():
                with gr.Column(scale=1):
                    chart_stock = gr.Textbox(
                        label="股票代码",
                        value="600519",
                        placeholder="输入6位代码，如 600519（茅台）、000977（浪潮）、688981（中芯）"
                    )
                    chart_days = gr.Slider(
                        label="数据天数",
                        minimum=20,
                        maximum=180,
                        value=60,
                        step=10
                    )
                    chart_type = gr.Radio(
                        choices=["K线图+均线+成交量", "MACD 指标", "量价分析", "大盘指数对比"],
                        label="图表类型",
                        value="K线图+均线+成交量"
                    )
                    chart_btn = gr.Button("📊 生成图表", variant="primary")
                    gr.Markdown("""
                    **常用代码速查：**
                    - `600519` 贵州茅台
                    - `000977` 浪潮信息
                    - `688981` 中芯国际
                    - `002230` 科大讯飞
                    - `300750` 宁德时代
                    """)

                with gr.Column(scale=2):
                    chart_output = gr.Plot(label="技术分析图表")

            chart_btn.click(
                update_chart,
                inputs=[chart_stock, chart_days, chart_type],
                outputs=chart_output
            )

        # ==============================
        # Tab 3: 智能问答
        # ==============================
        with gr.Tab("💬 智能问答"):
            gr.Markdown("### 💬 AI 投资助手（零 Token 成本）")
            gr.Markdown("基于当日分析数据的规则匹配问答。试试问：「今天适合买什么？」「AI板块走势如何？」「分析一下688981」")

            qa_chatbot = gr.Chatbot(
                label="对话记录",
                height=400,
                type="messages",
            )
            with gr.Row():
                qa_input = gr.Textbox(
                    label="输入问题",
                    placeholder="例如：今天适合买什么？ / AI板块走势如何？ / 分析一下688981 / 今日总结",
                    scale=4,
                )
                with gr.Column(scale=1):
                    qa_send = gr.Button("💬 发送", variant="primary")
                    qa_clear = gr.Button("🗑️ 清空对话")

            qa_send.click(
                chat_qa,
                inputs=[qa_input, qa_chatbot],
                outputs=[qa_input, qa_chatbot]
            )
            qa_input.submit(
                chat_qa,
                inputs=[qa_input, qa_chatbot],
                outputs=[qa_input, qa_chatbot]
            )
            qa_clear.click(
                clear_chat,
                outputs=[qa_input, qa_chatbot]
            )

        # ==============================
        # Tab 4: 历史报告
        # ==============================
        with gr.Tab("📁 历史报告"):
            gr.Markdown("### 📁 历史每日简报浏览")
            gr.Markdown("查看过去生成的每日分析报告，支持按日期追溯。")

            with gr.Row():
                with gr.Column(scale=1):
                    refresh_list_btn = gr.Button("🔄 刷新报告列表")
                    report_list_md = gr.Markdown("点击「刷新报告列表」加载...")
                    report_selector = gr.Dropdown(
                        label="选择报告",
                        choices=[],
                        interactive=True,
                    )

                with gr.Column(scale=2):
                    history_report_title = gr.Markdown("")
                    history_report_content = gr.Markdown(
                        "👈 请先点击「刷新报告列表」，然后从下拉菜单选择要查看的报告",
                    )

            refresh_list_btn.click(
                list_history_reports,
                outputs=[report_list_md, report_selector]
            )
            report_selector.change(
                view_history_report,
                inputs=report_selector,
                outputs=[history_report_content, history_report_title]
            )

    return demo


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)
