import akshare as ak
import pandas as pd
from datetime import datetime


# ========== 成员1 大盘数据：指数、整体行情、宏观新闻 ==========
def get_market_index():
    """获取沪深大盘指数"""
    df = ak.stock_sh_index()
    return df.to_string()


def get_macro_news():
    """获取财经综合新闻（宏观），返回结构化DataFrame"""
    df = ak.stock_news_em()
    # 重命名列以兼容中英文键名
    rename_map = {}
    if "标题" in df.columns:
        rename_map["标题"] = "title"
    if "发布时间" in df.columns:
        rename_map["发布时间"] = "timestamp"
    if "内容" in df.columns:
        rename_map["内容"] = "content"
    if "来源" in df.columns:
        rename_map["来源"] = "source"
    if rename_map:
        df = df.rename(columns=rename_map)
    # 如果没有 source 列，补充默认来源
    if "source" not in df.columns:
        df["source"] = "东方财富"
    if "content" not in df.columns:
        df["content"] = ""
    return df.head(10)


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
    """获取全部数据，结构化数据用于下游处理，字符串用于LLM prompt"""
    news_df = get_macro_news()
    # 为 LLM prompt 准备字符串形式
    news_str = news_df[["title", "timestamp"]].to_string() if hasattr(news_df, "to_string") else str(news_df)

    data = {
        "大盘指数": get_market_index(),
        "宏观新闻": news_str,
        "宏观新闻_结构化": news_df,   # 保留结构化版本供打分等下游使用
        "行业板块": get_industry_board(),
        "个股行情": get_stock_daily(),
        "个股财报": get_stock_finance()
    }
    return data
