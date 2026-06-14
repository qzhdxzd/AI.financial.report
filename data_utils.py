import akshare as ak
import pandas as pd
from datetime import datetime

# ========== 成员1 大盘数据：指数、整体行情、宏观新闻 ==========
def get_market_index():
    """获取沪深大盘指数"""
    df = ak.stock_sh_index()
    return df.to_string()

def get_macro_news():
    """获取财经综合新闻（宏观）"""
    df = ak.stock_news_em()
    # 只取前10条精简展示，避免文本过长、浪费Token
    return df[["标题", "发布时间"]].head(10).to_string()

# ========== 成员2 板块数据：行业板块、行业新闻 ==========
def get_industry_board():
    """获取行业板块涨跌数据"""
    df = ak.stock_board_industry_name_em()
    return df[["板块名称", "涨跌幅", "涨跌数"]].head(15).to_string()

# ========== 成员3 个股数据：个股行情、简易财报 ==========
def get_stock_daily(stock_code="600519", start="20260601", end="20260613"):
    """获取指定个股日K数据"""
    df = ak.stock_zh_a_daily(symbol=stock_code, start_date=start, end_date=end)
    return df[["开盘", "收盘", "最高", "最低", "成交量"]].to_string()

def get_stock_finance(stock_code="600519"):
    """获取个股财报摘要"""
    df = ak.stock_profit_sheet_by_report_em(symbol=stock_code)
    return df[["报告期", "营业收入", "净利润"]].head(5).to_string()

# 统一打包全部数据，供LLM调用
def get_all_data():
    data = {
        "大盘指数": get_market_index(),
        "宏观新闻": get_macro_news(),
        "行业板块": get_industry_board(),
        "个股行情": get_stock_daily(),
        "个股财报": get_stock_finance()
    }
    return data