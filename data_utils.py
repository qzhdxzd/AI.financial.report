import akshare as ak
import pandas as pd
from datetime import datetime, timedelta


# ========== 成员1 大盘数据：指数、整体行情、宏观新闻 ==========
def get_market_index():
    """获取沪深大盘指数（多级回退）"""
    # 方案1：实时行情
    try:
        df = ak.stock_zh_index_spot_em()
        sh = df[df['名称'].isin(['上证指数', '上证综指'])]
        sz = df[df['名称'] == '深证成指']
        if sz.empty:
            sz = df[df['代码'].isin(['399001', 'sz399001'])]
        if not sh.empty and not sz.empty:
            return (f"上证指数: {sh['最新价'].iloc[0]} ({sh['涨跌幅'].iloc[0]}%)\n"
                    f"深证成指: {sz['最新价'].iloc[0]} ({sz['涨跌幅'].iloc[0]}%)")
    except Exception:
        pass

    # 方案2：历史日线
    try:
        df = ak.stock_zh_index_daily(symbol="sh000001")
        latest = df.iloc[-1]
        return f"上证指数: {latest['close']} (开{latest['open']} 高{latest['high']} 低{latest['low']})"
    except Exception:
        pass

    # 方案3：旧版接口
    try:
        df = ak.stock_sh_index()
        return df.to_string()
    except Exception:
        return "大盘指数数据暂不可用"


def get_macro_news():
    """获取财经综合新闻（宏观），返回结构化DataFrame"""
    try:
        df = ak.stock_news_em()
    except Exception as e:
        # 网络故障时返回空 DataFrame（包含必要字段）
        return pd.DataFrame(columns=["title", "timestamp", "content", "source"])

    # 重命名列以兼容中英文键名（akshare 实际列名为中文）
    rename_map = {}
    if "新闻标题" in df.columns:
        rename_map["新闻标题"] = "title"
    if "标题" in df.columns and "新闻标题" not in df.columns:
        rename_map["标题"] = "title"
    if "发布时间" in df.columns:
        rename_map["发布时间"] = "timestamp"
    if "新闻内容" in df.columns:
        rename_map["新闻内容"] = "content"
    if "内容" in df.columns and "新闻内容" not in df.columns:
        rename_map["内容"] = "content"
    if "文章来源" in df.columns:
        rename_map["文章来源"] = "source"
    if "来源" in df.columns and "文章来源" not in df.columns:
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
    try:
        df = ak.stock_board_industry_name_em()
        return df[["板块名称", "涨跌幅", "涨跌数"]].head(15).to_string()
    except Exception as e:
        return f"行业板块数据暂不可用 ({e})"


# ========== 成员3 个股数据：个股行情、简易财报 ==========
def get_stock_daily(stock_code="600519", days=30):
    """获取指定个股近N个交易日K线数据"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")  # 多取一些覆盖非交易日
    try:
        df = ak.stock_zh_a_daily(symbol=stock_code, start_date=start_date, end_date=end_date)
        return df[["开盘", "收盘", "最高", "最低", "成交量"]].tail(days).to_string()
    except Exception as e:
        return f"个股 {stock_code} 行情获取失败: {e}"


def get_stock_finance(stock_code="600519"):
    """获取个股财报摘要"""
    try:
        df = ak.stock_profit_sheet_by_report_em(symbol=stock_code)
        return df[["报告期", "营业收入", "净利润"]].head(5).to_string()
    except Exception as e:
        return f"个股 {stock_code} 财报获取失败: {e}"


# 统一打包全部数据，供LLM调用
def get_all_data(stock_code="600519"):
    """获取全部数据，结构化数据用于下游处理，字符串用于LLM prompt"""
    news_df = get_macro_news()
    # 为 LLM prompt 准备字符串形式（处理空 DataFrame 情况）
    if hasattr(news_df, "to_string") and not news_df.empty:
        if "title" in news_df.columns and "timestamp" in news_df.columns:
            news_str = news_df[["title", "timestamp"]].to_string()
        else:
            news_str = news_df.to_string()
    else:
        news_str = str(news_df) if not (hasattr(news_df, "empty") and news_df.empty) else "暂无宏观新闻"

    data = {
        "大盘指数": get_market_index(),
        "宏观新闻": news_str,
        "宏观新闻_结构化": news_df,   # 保留结构化版本供打分等下游使用
        "行业板块": get_industry_board(),
        "个股行情": get_stock_daily(stock_code=stock_code),
        "个股财报": get_stock_finance(stock_code=stock_code)
    }
    return data
