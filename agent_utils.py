import os
import requests

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


def llm_chat(prompt: str, max_tokens: int = 1500) -> str:
    """调用 DeepSeek API 进行大模型对话"""
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
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            error = resp.json().get("error", {}).get("message", "未知错误")
            return f"⚠️ API 调用失败: {error}"
    except Exception as e:
        return f"⚠️ 请求异常: {e}"


# ========== Agent1 大盘分析（成员1负责） ==========
def agent_market_analysis(index_data, news_data):
    prompt = f"""
你是大盘分析师，请根据以下大盘指数、宏观财经新闻，分析今日整体市场走势、市场情绪。
数据：
大盘指数：{index_data}
宏观新闻：{news_data}
输出要求：简明总结走势、判断市场情绪（乐观/中性/悲观）。
"""
    return llm_chat(prompt)


# ========== Agent2 板块分析（成员2负责） ==========
def agent_board_analysis(board_data):
    prompt = f"""
你是行业板块分析师，根据下方板块涨跌数据，分析热门板块、领涨/领跌板块，
并给出情绪评分（范围：-1 极度利空 ~ +1 极度利好），格式：板块名称 | 评分 | 分析理由
板块数据：{board_data}
"""
    return llm_chat(prompt)


# ========== Agent3 个股分析 + 报告汇总（成员3负责） ==========
def agent_stock_analysis(stock_data, finance_data):
    prompt = f"""
你是个股分析师，结合个股行情数据、财报数据，分析个股短期走势与基本面情况，给出操作建议。
行情数据：{stock_data}
财报数据：{finance_data}
"""
    return llm_chat(prompt)


# 总汇总智能体：整合三个Agent结果，生成最终日报
def agent_summary(market_res, board_res, stock_res):
    prompt = f"""
整合以下三份分析报告，生成一份完整的《A股每日分析报告》，包含市场总结、板块解读、个股建议、整体风险提示。
1. 大盘分析：{market_res}
2. 板块分析：{board_res}
3. 个股分析：{stock_res}
输出正式、结构化的日报。
"""
    return llm_chat(prompt)
