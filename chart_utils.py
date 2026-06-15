#!/usr/bin/env python3
"""
图表工具模块 - K线图 / MACD / 成交量
使用 AKShare 获取行情数据，Plotly 绘制交互式图表
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ---------- 数据获取 ----------

def _fetch_stock_data(stock_code: str, days: int = 60):
    """获取个股日线数据（兼容多种代码格式）"""
    import akshare as ak

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

    # 统一代码格式：纯数字 → sh/sz 前缀
    symbol = stock_code
    if stock_code.isdigit():
        if stock_code.startswith(("6", "9")):
            symbol = f"sh{stock_code}"
        else:
            symbol = f"sz{stock_code}"

    # 方案1：通用个股日线
    try:
        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # 方案2：尝试不带前缀
    try:
        df = ak.stock_zh_a_daily(symbol=stock_code, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    # 方案3：指数日线
    try:
        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is not None and not df.empty:
            return df.tail(days)
    except Exception:
        pass

    return None


def _fetch_index_data(index_code: str = "sh000001", days: int = 60):
    """获取指数日线数据"""
    import akshare as ak

    try:
        df = ak.stock_zh_index_daily(symbol=index_code)
        if df is not None and not df.empty:
            return df.tail(days)
    except Exception:
        pass
    return None


# ---------- MACD 计算 ----------

def _calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """计算 MACD 指标"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = 2 * (dif - dea)
    return dif, dea, macd_bar


def _calc_ma(close: pd.Series, periods=(5, 10, 20, 60)):
    """计算多周期均线"""
    mas = {}
    for p in periods:
        mas[f"MA{p}"] = close.rolling(window=p).mean()
    return mas


# ---------- 图表绘制 ----------

def plot_kline(stock_code: str = "600519", days: int = 60, stock_name: str = ""):
    """
    绘制 K 线图 + 均线 + 成交量
    返回 plotly Figure 对象，可直接用于 Gradio Plot 组件
    """
    df = _fetch_stock_data(stock_code, days)

    if df is None or df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text=f"⚠️ 无法获取 {stock_code} 的行情数据<br>请检查股票代码或网络连接",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color="#e74c3c")
        )
        fig.update_layout(
            template="plotly_dark",
            height=500,
            title=f"{stock_name or stock_code} - 数据获取失败"
        )
        return fig

    # 确保列名兼容
    df = df.rename(columns={
        "open": "开盘", "high": "最高", "low": "最低", "close": "收盘",
        "volume": "成交量", "date": "日期"
    })
    # 兼容英文列名
    col_open = "开盘" if "开盘" in df.columns else "open"
    col_high = "最高" if "最高" in df.columns else "high"
    col_low = "最低" if "最低" in df.columns else "low"
    col_close = "收盘" if "收盘" in df.columns else "close"
    col_vol = "成交量" if "成交量" in df.columns else "volume"
    col_date = "日期" if "日期" in df.columns else "date"

    # 计算均线
    close = df[col_close]
    mas = _calc_ma(close)

    # 创建子图（K线在上，成交量在下）
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
        subplot_titles=(f"{stock_name or stock_code} K线图", "成交量")
    )

    # ---- K 线 ----
    fig.add_trace(
        go.Candlestick(
            x=df.index if col_date not in df.columns else df[col_date],
            open=df[col_open],
            high=df[col_high],
            low=df[col_low],
            close=df[col_close],
            name="K线",
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
        ),
        row=1, col=1
    )

    # 均线
    ma_colors = {"MA5": "#f1c40f", "MA10": "#3498db", "MA20": "#e67e22", "MA60": "#9b59b6"}
    for ma_name, ma_series in mas.items():
        fig.add_trace(
            go.Scatter(
                x=df.index if col_date not in df.columns else df[col_date],
                y=ma_series,
                mode="lines",
                name=ma_name,
                line=dict(width=1.2, color=ma_colors.get(ma_name, "#888")),
            ),
            row=1, col=1
        )

    # ---- 成交量 ----
    # 根据涨跌上色
    vol_colors = [
        "#ef5350" if df[col_close].iloc[i] >= df[col_open].iloc[i] else "#26a69a"
        for i in range(len(df))
    ]
    fig.add_trace(
        go.Bar(
            x=df.index if col_date not in df.columns else df[col_date],
            y=df[col_vol],
            name="成交量",
            marker_color=vol_colors,
            opacity=0.6,
        ),
        row=2, col=1
    )

    # ---- 布局 ----
    fig.update_layout(
        template="plotly_dark",
        height=650,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(title_text="", row=2, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)

    return fig


def plot_macd(stock_code: str = "600519", days: int = 60, stock_name: str = ""):
    """
    绘制 MACD 指标图
    返回 plotly Figure 对象
    """
    df = _fetch_stock_data(stock_code, days)

    if df is None or df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text=f"⚠️ 无法获取 {stock_code} 的行情数据",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color="#e74c3c")
        )
        fig.update_layout(template="plotly_dark", height=400)
        return fig

    col_close = "收盘" if "收盘" in df.columns else "close"
    col_date = "日期" if "日期" in df.columns else "date"
    close = df[col_close]

    dif, dea, macd_bar = _calc_macd(close)
    x_axis = df.index if col_date not in df.columns else df[col_date]

    bar_colors = ["#ef5350" if v >= 0 else "#26a69a" for v in macd_bar]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05, row_heights=[0.55, 0.45])

    # 价格 + DIF/DEA
    fig.add_trace(
        go.Scatter(x=x_axis, y=close, mode="lines", name="收盘价",
                   line=dict(color="#f5c2e7", width=1.5)),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(x=x_axis, y=dif, mode="lines", name="DIF",
                   line=dict(color="#f1c40f", width=1)),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(x=x_axis, y=dea, mode="lines", name="DEA",
                   line=dict(color="#3498db", width=1)),
        row=2, col=1
    )

    # MACD 柱
    fig.add_trace(
        go.Bar(x=x_axis, y=macd_bar, name="MACD柱",
               marker_color=bar_colors, opacity=0.7),
        row=2, col=1
    )

    fig.update_layout(
        template="plotly_dark",
        height=550,
        title=f"{stock_name or stock_code} MACD 指标",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="MACD", row=2, col=1)

    return fig


def plot_volume_analysis(stock_code: str = "600519", days: int = 60, stock_name: str = ""):
    """
    绘制成交量分析图（量价关系）
    返回 plotly Figure 对象
    """
    df = _fetch_stock_data(stock_code, days)

    if df is None or df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text=f"⚠️ 无法获取 {stock_code} 的行情数据",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color="#e74c3c")
        )
        fig.update_layout(template="plotly_dark", height=400)
        return fig

    col_open = "开盘" if "开盘" in df.columns else "open"
    col_high = "最高" if "最高" in df.columns else "high"
    col_low = "最低" if "最低" in df.columns else "low"
    col_close = "收盘" if "收盘" in df.columns else "close"
    col_vol = "成交量" if "成交量" in df.columns else "volume"
    col_date = "日期" if "日期" in df.columns else "date"

    x_axis = df.index if col_date not in df.columns else df[col_date]
    close = df[col_close]

    # 量比（当日成交量 / 5日均量）
    vol_ma5 = df[col_vol].rolling(5).mean()
    vol_ratio = df[col_vol] / vol_ma5

    # 涨跌幅
    chg_pct = close.pct_change() * 100

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.4, 0.3, 0.3],
        subplot_titles=("价格走势", "成交量 + 5日均量", "量比（成交量/5日均量）")
    )

    # 价格
    fig.add_trace(
        go.Scatter(x=x_axis, y=close, mode="lines", name="收盘价",
                   line=dict(color="#f5c2e7", width=1.5)),
        row=1, col=1
    )

    # 成交量
    fig.add_trace(
        go.Bar(x=x_axis, y=df[col_vol], name="成交量", marker_color="#a6adc8", opacity=0.6),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(x=x_axis, y=vol_ma5, mode="lines", name="5日均量",
                   line=dict(color="#f39c12", width=1.5)),
        row=2, col=1
    )

    # 量比
    qb_colors = ["#ef5350" if v > 1.5 else ("#f39c12" if v > 1 else "#26a69a") for v in vol_ratio]
    fig.add_trace(
        go.Bar(x=x_axis, y=vol_ratio, name="量比", marker_color=qb_colors, opacity=0.7),
        row=3, col=1
    )
    # 量比=1 参考线
    fig.add_hline(y=1, line_dash="dash", line_color="#6c7086", row=3, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=650,
        title=f"{stock_name or stock_code} 量价分析",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=50, b=10),
    )

    return fig


def plot_index_overview():
    """绘制大盘指数概览（上证 + 深证走势对比）"""
    sh = _fetch_index_data("sh000001", days=30)
    sz = _fetch_index_data("sz399001", days=30)

    fig = go.Figure()

    if sh is not None and not sh.empty:
        # 归一化：以第一天为基准 100
        sh_close = sh["close"]
        sh_norm = sh_close / sh_close.iloc[0] * 100
        fig.add_trace(go.Scatter(
            x=sh.index, y=sh_norm, mode="lines", name="上证指数",
            line=dict(color="#ef5350", width=2)
        ))

    if sz is not None and not sz.empty:
        sz_close = sz["close"]
        sz_norm = sz_close / sz_close.iloc[0] * 100
        fig.add_trace(go.Scatter(
            x=sz.index, y=sz_norm, mode="lines", name="深证成指",
            line=dict(color="#3498db", width=2)
        ))

    if (sh is None or sh.empty) and (sz is None or sz.empty):
        fig.add_annotation(
            text="⚠️ 无法获取大盘指数数据",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color="#e74c3c")
        )

    fig.update_layout(
        template="plotly_dark",
        height=400,
        title="大盘指数近30日走势对比（归一化 基准=100）",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    fig.update_yaxes(title_text="归一化指数")

    return fig
