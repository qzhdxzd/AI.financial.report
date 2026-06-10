#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ModelScope 环境优化版科技新闻采集器 v4.1
- 自动适配 cloudscraper，若不可用则跳过 36kr
- 优化新浪财经、东方财富、财联社接口，采用更稳定的 7x24 快讯官方 API 
- 财联社支持 AkShare/Wap双重保底，彻底解决抓取不到大部分数据源的问题
- 依赖稳定 RSS 源和 AKShare，确保数据量
- 本地关键词回退，无需 DeepSeek 也能筛选
"""

import json
import os
import hashlib
import re
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

# ---------- 可选依赖 ----------
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    print("⚠️ cloudscraper 未安装，36kr 将不采集（安装: pip install cloudscraper）")

# ---------- 配置 ----------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEBUG_MODE = os.environ.get("DEBUG", "false").lower() in ("true", "1")

# 保底模拟新闻（3条）
FALLBACK_NEWS = [
    {
        "title": "英伟达发布新一代AI芯片H200，算力提升3倍",
        "content": "英伟达今日宣布推出新一代AI加速卡H200，预计将带动全球AI算力需求大幅增长。",
        "source": "模拟数据",
        "category": "AI芯片",
        "sentiment": "positive"
    },
    {
        "title": "中芯国际季度营收超预期，半导体行业回暖",
        "content": "中芯国际公告显示，三季度营收同比增长34%，超出市场预期，行业景气度回升。",
        "source": "模拟数据",
        "category": "半导体",
        "sentiment": "positive"
    },
    {
        "title": "工信部：加快推动人工智能与实体经济深度融合",
        "content": "工信部相关负责人表示，下一步将出台更多政策支持AI产业发展，推动大模型在工业场景落地。",
        "source": "模拟数据",
        "category": "AI",
        "sentiment": "positive"
    }
]

# ---------- 本地关键词过滤器 ----------
TECH_KEYWORDS = [
    "人工智能", "AI", "机器学习", "深度学习", "神经网络", "大模型", "ChatGPT", "GPT",
    "芯片", "半导体", "集成电路", "晶圆", "光刻", "EUV", "GPU", "CPU", "NPU",
    "计算机", "软件", "硬件", "服务器", "数据中心", "云计算", "边缘计算",
    "互联网", "移动互联网", "物联网", "IoT", "5G", "6G", "通信", "卫星互联网",
    "大数据", "数据分析", "数据挖掘", "数据库", "区块链", "Web3",
    "虚拟现实", "VR", "增强现实", "AR", "混合现实", "MR", "元宇宙",
    "自动驾驶", "无人驾驶", "智能汽车", "新能源车", "电动车", "动力电池",
    "机器人", "工业机器人", "人形机器人", "无人机",
    "生物技术", "基因编辑", "脑机接口", "金融科技", "量化交易",
    "网络安全", "信息安全", "加密", "漏洞", "黑客",
    "量子计算", "量子通信", "光子计算",
    "数字人", "AIGC", "生成式AI",
    "iPhone", "iOS", "Android", "华为", "小米", "OPPO", "vivo", "三星", "英伟达", "台积电",
    "特斯拉", "OpenAI", "微软", "谷歌", "Meta", "苹果", "字节跳动", "腾讯", "阿里",
]

NON_TECH_INDICATORS = [
    "娱乐", "明星", "影视", "电视剧", "电影", "综艺", "八卦", "绯闻",
    "体育", "足球", "篮球", "NBA", "世界杯", "奥运会", "田径", "游泳",
    "美食", "旅游", "酒店", "时尚", "美妆", "穿搭",
    "汽车评测", "房产", "家居", "装修", "教育政策", "考试", "留学",
    "育儿", "健康", "养生", "医疗", "疫情", "疫苗", "中医",
    "天气", "交通管制", "限行", "菜价", "油价",
]

# ---------- 工具函数 ----------
def is_similar(t1: str, t2: str, thresh: float = 0.6) -> bool:
    return SequenceMatcher(None, t1, t2).ratio() > thresh

def clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()

# 全局 Session
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
})

def safe_request(url: str, timeout: int = 15, headers: Optional[dict] = None) -> Optional[requests.Response]:
    if headers:
        session.headers.update(headers)
    for _ in range(2):
        try:
            resp = session.get(url, timeout=timeout)
            if DEBUG_MODE:
                print(f"       [DEBUG] {url} -> {resp.status_code} (len={len(resp.text)})")
            if resp.status_code == 200:
                return resp
        except Exception as e:
            if DEBUG_MODE:
                print(f"       [DEBUG] {url} 请求失败: {e}")
        time.sleep(1)
    return None

def call_deepseek(prompt: str, max_tokens: int = 80) -> Optional[str]:
    if not DEEPSEEK_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None

def local_classify(title: str, content: str) -> Tuple[bool, str, str]:
    text = f"{title} {content}".lower()
    for w in NON_TECH_INDICATORS:
        if w in text:
            return (False, "非科技", "neutral")
    matched_cat = "科技"
    for kw in TECH_KEYWORDS:
        if kw.lower() in text:
            matched_cat = kw
            break
    else:
        return (False, "非科技", "neutral")
    # 情感
    pos_words = ["突破", "发布", "增长", "提升", "利好", "创新", "合作", "投资", "上市", "交付"]
    neg_words = ["下滑", "暴跌", "亏损", "裁员", "诉讼", "违规", "召回", "漏洞", "攻击", "禁用"]
    pos_cnt = sum(1 for w in pos_words if w in text)
    neg_cnt = sum(1 for w in neg_words if w in text)
    sentiment = "neutral"
    if pos_cnt > neg_cnt:
        sentiment = "positive"
    elif neg_cnt > pos_cnt:
        sentiment = "negative"
    return (True, matched_cat, sentiment)

def deepseek_classify(title: str, content: str) -> Tuple[bool, str, str]:
    if not DEEPSEEK_API_KEY:
        return local_classify(title, content)
    prompt = f"""请仔细判断以下新闻是否属于科技领域。科技新闻主要包括：AI、人工智能、机器学习、深度学习、芯片、半导体、集成电路、计算机、软件、硬件、互联网、移动互联网、大数据、云计算、物联网、5G、6G、区块链、虚拟现实、增强现实、自动驾驶、机器人、新能源车、生物技术、金融科技、通讯技术、网络安全、游戏技术等相关内容。

如果是科技领域新闻，返回: {{"is_tech": true, "category": "具体科技领域", "sentiment": "positive/negative/neutral"}}
如果不是科技领域新闻，返回: {{"is_tech": false, "category": "非科技领域", "sentiment": "neutral"}}

标题：{title}
内容：{content[:300]}"""
    result = call_deepseek(prompt)
    if not result:
        return local_classify(title, content)
    try:
        data = json.loads(result)
        is_tech = data.get("is_tech", False)
        if not is_tech and any(ind in f"{title}{content}".lower() for ind in NON_TECH_INDICATORS):
            return (False, "非科技", "neutral")
        return (is_tech, data.get("category", "科技"), data.get("sentiment", "neutral"))
    except Exception:
        return local_classify(title, content)

def deepseek_summarize(content: str) -> str:
    if not content or len(content.strip()) < 10:
        return "内容较短，无详细内容。"
    if DEEPSEEK_API_KEY:
        prompt = f"""请对以下新闻内容生成一个简洁准确的概览，限制在100字以内，突出关键信息和技术要点：
内容：{content[:500]}"""
        result = call_deepseek(prompt, max_tokens=100)
        if result:
            return result.replace('"', '').replace("'", "").strip()
    return content[:100] + "..." if len(content) > 100 else content

# ==================== 各数据源采集函数 ====================

def fetch_akshare(stocks: List[str]) -> List[Dict]:
    if not AKSHARE_AVAILABLE:
        return []
    news = []
    for code in stocks:
        try:
            df = ak.stock_news_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    raw_content = clean_text(row.get('content', ''))
                    content = deepseek_summarize(raw_content) if raw_content else ""
                    news.append({
                        "title": clean_text(row.get('title', '')),
                        "content": content,
                        "timestamp": row.get('publish_time', datetime.now().isoformat()),
                        "source": "AKShare",
                        "url": row.get('url', '')
                    })
            time.sleep(0.5)
        except Exception as e:
            print(f"   AKShare {code} 失败: {e}")
    return news

def fetch_tushare() -> List[Dict]:
    try:
        import tushare as ts
        token = os.environ.get("TUSHARE_TOKEN", "")
        if not token:
            return []
        pro = ts.pro_api(token)
        df = pro.cctv_news(date=datetime.now().strftime('%Y%m%d'))
        news = []
        for _, row in df.iterrows():
            raw_content = clean_text(row.get('content', ''))
            content = deepseek_summarize(raw_content)
            news.append({
                "title": clean_text(row.get('title', '')),
                "content": content,
                "timestamp": row.get('date', datetime.now().isoformat()),
                "source": "Tushare",
                "url": ""
            })
        return news
    except ImportError:
        return []
    except Exception as e:
        print(f"   Tushare 失败: {e}")
        return []

def fetch_eastmoney() -> List[Dict]:
    """
    通过东方财富快讯官方 API 采集（替换原有不稳定且内容残缺的 AJAX 分页接口）
    """
    try:
        url = "https://fastnews.eastmoney.com/api/FastNews/GetFastNewsList?pageIndex=1&pageSize=30&ShowType=1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://kuaixun.eastmoney.com/"
        }
        resp = safe_request(url, headers=headers)
        if not resp:
            return []
        data = resp.json()
        news = []
        for item in data.get('Data', []):
            title = clean_text(item.get('Title', ''))
            raw_summary = clean_text(item.get('Digest', ''))
            if not title and not raw_summary:
                continue
            
            raw_content = raw_summary if raw_summary else title
            content = deepseek_summarize(raw_content)
            news.append({
                "title": title if title else raw_content[:25],
                "content": content,
                "timestamp": item.get('ShowTime', datetime.now().isoformat()),
                "source": "东方财富",
                "url": item.get('Url', 'https://kuaixun.eastmoney.com/')
            })
        return news
    except Exception as e:
        print(f"   东方财富失败: {e}")
        return []

def fetch_sina_finance() -> List[Dict]:
    """
    通过新浪财经 7x24 快讯公开最新 JSON API 采集（规避旧滚动接口 403 频率限制）
    """
    try:
        # zhibo_id=152 代表全天候综合财经/科技快讯流
        url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=30&zhibo_id=152"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn/7x24/"
        }
        resp = safe_request(url, headers=headers)
        if not resp:
            return []
        data = resp.json()
        items = data.get('result', {}).get('data', {}).get('feed', {}).get('list', [])
        news = []
        for item in items:
            raw_text = clean_text(item.get('rich_text', item.get('summary', '')))
            if not raw_text:
                continue
            title = clean_text(item.get('title', '')) or raw_text[:25]
            content = deepseek_summarize(raw_text)
            news.append({
                "title": title,
                "content": content,
                "timestamp": item.get('create_time', datetime.now().isoformat()),
                "source": "新浪财经",
                "url": item.get('docurl', 'https://finance.sina.com.cn/7x24/')
            })
        return news
    except Exception as e:
        print(f"   新浪财经失败: {e}")
        return []

def fetch_wallstreetcn() -> List[Dict]:
    api_urls = [
        "https://api-prod.wallstreetcn.com/apiv1/content/lives?channel=global&limit=30",
        "https://api-app-wallstreetcn-com-apifc.wallstcn.com/apiv1/content/lives?channel=global&limit=30"
    ]
    for url in api_urls:
        try:
            resp = safe_request(url)
            if not resp:
                continue
            data = resp.json()
            items = data.get('data', {}).get('items', [])
            if not items:
                continue
            news = []
            for item in items[:30]:
                raw_text = clean_text(item.get('content_text', ''))
                if not raw_text:
                    continue
                content = deepseek_summarize(raw_text)
                news.append({
                    "title": raw_text[:100],
                    "content": content,
                    "timestamp": item.get('created_at', datetime.now().isoformat()),
                    "source": "华尔街见闻",
                    "url": f"https://wallstreetcn.com/live/{item.get('id','')}" if item.get('id') else ''
                })
            if news:
                return news
        except Exception as e:
            print(f"   华尔街见闻 API 失败: {e}")
    # 网页回退
    try:
        resp = safe_request("https://www.wallstreetcn.com/live/global")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.live-list-item .title a') or soup.select('.article-item .title a')
        news = []
        for item in items[:20]:
            title = clean_text(item.get_text())
            if title:
                content = deepseek_summarize(title)
                news.append({
                    "title": title,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "source": "华尔街见闻",
                    "url": item.get('href', '')
                })
        return news
    except Exception as e:
        print(f"   华尔街见闻网页失败: {e}")
        return []

# RSS 稳定源
def fetch_rss_sina_tech() -> List[Dict]:
    try:
        resp = safe_request("https://tech.sina.com.cn/rss/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'xml')
        items = soup.find_all('item')[:20]
        news = []
        for item in items:
            title = clean_text(item.title.text)
            desc = clean_text(item.description.text)
            content = deepseek_summarize(desc)
            news.append({
                "title": title,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "source": "新浪科技RSS",
                "url": item.link.text
            })
        return news
    except Exception as e:
        print(f"   新浪科技RSS失败: {e}")
        return []

def fetch_rss_163_tech() -> List[Dict]:
    try:
        resp = safe_request("https://tech.163.com/special/tech_rss/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'xml')
        items = soup.find_all('item')[:20]
        news = []
        for item in items:
            title = clean_text(item.title.text)
            desc = clean_text(item.description.text)
            content = deepseek_summarize(desc)
            news.append({
                "title": title,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "source": "网易科技RSS",
                "url": item.link.text
            })
        return news
    except Exception as e:
        print(f"   网易科技RSS失败: {e}")
        return []

def fetch_rss_huxiu() -> List[Dict]:
    try:
        resp = safe_request("https://www.huxiu.com/rss/0.xml")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'xml')
        items = soup.find_all('item')[:20]
        news = []
        for item in items:
            title = clean_text(item.title.text)
            desc = clean_text(item.description.text)
            content = deepseek_summarize(desc)
            news.append({
                "title": title,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "source": "虎嗅RSS",
                "url": item.link.text
            })
        return news
    except Exception as e:
        print(f"   虎嗅RSS失败: {e}")
        return []

# 其他网页源（需 BS4 解析）
def fetch_tencent_tech() -> List[Dict]:
    try:
        resp = safe_request("https://tech.qq.com/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.Q-tpWrap h3 a, .list-hd h3 a')[:15]
        news = []
        for a in items:
            title = clean_text(a.get_text())
            if title and len(title) > 5:
                content = deepseek_summarize(title)
                news.append({
                    "title": title,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "source": "腾讯科技",
                    "url": a.get('href', '')
                })
        return news
    except Exception as e:
        print(f"   腾讯科技失败: {e}")
        return []

def fetch_it_home() -> List[Dict]:
    try:
        resp = safe_request("https://www.ithome.com/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.bx ul li a')[:15]
        news = []
        for a in items:
            title = clean_text(a.get_text())
            if title and len(title) > 5:
                content = deepseek_summarize(title)
                news.append({
                    "title": title,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "source": "IT之家",
                    "url": a.get('href', '')
                })
        return news
    except Exception as e:
        print(f"   IT之家失败: {e}")
        return []

def fetch_cls() -> List[Dict]:
    """
    财联社多保底采集：
    1. 优先尝试 AkShare 的内置算法解密方案（最稳定且无视 Cloudflare 风控）
    2. 若失效则请求免签的手机端 Wap 接口（无需 cloudscraper 支持）
    3. 最后退回到原有 PC 网页端 cloudscraper 爬取逻辑
    """
    news = []

    # 方案一：使用 AkShare 自带的财联社电报解析接口
    if AKSHARE_AVAILABLE:
        try:
            df = ak.stock_telegraph_cls()
            if df is not None and not df.empty:
                for _, row in df.head(30).iterrows():
                    raw_content = clean_text(row.get("滚动内容") or row.get("content") or "")
                    if not raw_content:
                        continue
                    title = clean_text(row.get("滚动标题") or row.get("title") or raw_content[:25])
                    content = deepseek_summarize(raw_content)
                    news.append({
                        "title": title,
                        "content": content,
                        "timestamp": datetime.now().isoformat(),
                        "source": "财联社",
                        "url": "https://www.cls.cn/telegraph"
                    })
                if news:
                    if DEBUG_MODE:
                        print("       [DEBUG] 财联社：通过 AkShare 成功获取数据")
                    return news
        except Exception as e:
            if DEBUG_MODE:
                print(f"       [DEBUG] 财联社 AkShare 接口失败，尝试下一方案: {e}")

    # 方案二：直接通过移动端公开的轻量版 Wap 接口（对反爬和 CF 极其宽松）
    try:
        url = f"https://www.cls.cn/v1/roll/get_roll_list?category=express&last_time={int(time.time())}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/504.1",
            "Referer": "https://m.cls.cn/",
            "Accept": "application/json"
        }
        resp = safe_request(url, headers=headers)
        if resp and resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("roll_list", [])
            for item in items[:30]:
                raw_content = clean_text(item.get("content", ""))
                if not raw_content:
                    continue
                title = clean_text(item.get("title", "")) or raw_content[:25]
                content = deepseek_summarize(raw_content)
                news.append({
                    "title": title,
                    "content": content,
                    "timestamp": item.get("ctime") or datetime.now().isoformat(),
                    "source": "财联社",
                    "url": f"https://www.cls.cn/detail/{item.get('id')}"
                })
            if news:
                if DEBUG_MODE:
                    print("       [DEBUG] 财联社：通过 Wap 轻量接口成功获取数据")
                return news
    except Exception as e:
        if DEBUG_MODE:
            print(f"       [DEBUG] 财联社 Wap 接口失败，尝试下一方案: {e}")

    # 方案三：退回原有 cloudscraper 方案
    if CLOUDSCRAPER_AVAILABLE:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.cls.cn/telegraph",
            "Accept": "application/json",
        }
        scraper = cloudscraper.create_scraper()
        urls = [
            "https://www.cls.cn/api/telegraph/list?rn=30",
            "https://www.cls.cn/api/telegraph/list?rn=30&type=all",
        ]
        for url in urls:
            try:
                resp = scraper.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                items = data.get("data", {}).get("roll_data", []) or data.get("roll_data", [])
                for item in items[:30]:
                    title = clean_text(item.get("title") or item.get("content", ""))
                    raw_content = clean_text(item.get("content", "")) or title
                    content = deepseek_summarize(raw_content)
                    news.append({
                        "title": title[:25] if title == raw_content else title,
                        "content": content,
                        "timestamp": item.get("ctime") or datetime.now().isoformat(),
                        "source": "财联社",
                        "url": item.get("shareurl") or f"https://www.cls.cn/detail/{item.get('id')}"
                    })
                if news:
                    return news
            except Exception as e:
                if DEBUG_MODE:
                    print(f"       [DEBUG] 财联社 cloudscraper URL 失败: {e}")
    return []

def fetch_36kr() -> List[Dict]:
    if not CLOUDSCRAPER_AVAILABLE:
        return []
    headers = {
        "Referer": "https://36kr.com/",
        "Accept": "application/json",
    }
    scraper = cloudscraper.create_scraper()
    urls = [
        "https://36kr.com/api/information-flow/article/latest?per_page=20",
        "https://36kr.com/api/newsflash?per_page=20",
    ]
    for url in urls:
        try:
            resp = scraper.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            items = data.get("data", {}).get("items") or data.get("data", [])
            if items:
                news = []
                for item in items[:20]:
                    title = clean_text(item.get("title") or item.get("item_title", ""))
                    summary = clean_text(item.get("summary") or item.get("item_summary", ""))
                    content = deepseek_summarize(summary) if summary else deepseek_summarize(title)
                    news.append({
                        "title": title,
                        "content": content,
                        "timestamp": item.get("published_at") or datetime.now().isoformat(),
                        "source": "36氪",
                        "url": item.get("url") or f"https://36kr.com/p/{item.get('id')}"
                    })
                return news
        except Exception as e:
            if DEBUG_MODE:
                print(f"   36kr cloudscraper 失败: {e}")
    return []

# ==================== 主采集器 ====================
class TechNewsCollector:
    def __init__(self, use_mock=False, use_llm_filter=True, selected_sources=None):
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter and bool(DEEPSEEK_API_KEY)
        # 默认源：将财联社移回默认列表，因为即便没有 cloudscraper，它依然可以通过 AkShare/Wap 独立平稳工作
        if selected_sources is None:
            selected_sources = [
                "AKShare", "Tushare", "东方财富", "新浪财经",
                "华尔街见闻", "财联社",
                "新浪科技RSS", "网易科技RSS", "虎嗅RSS",
                "腾讯科技", "IT之家",
            ]
            if CLOUDSCRAPER_AVAILABLE:
                selected_sources += ["36氪"]
        self.sources = selected_sources
        if not DEEPSEEK_API_KEY:
            print("⚠️ 未设置 DEEPSEEK_API_KEY，将使用本地关键词过滤")
        else:
            print("✓ DeepSeek API 已配置")

    def _get_fallback_news(self):
        now = datetime.now().isoformat()
        return [{
            "id": f"fallback_{i}",
            "timestamp": now,
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
        } for i, item in enumerate(FALLBACK_NEWS)]

    def collect(self) -> List[Dict]:
        if self.use_mock:
            print("使用模拟数据模式")
            return self._get_fallback_news()

        source_functions = {
            "AKShare": fetch_akshare,
            "Tushare": fetch_tushare,
            "东方财富": fetch_eastmoney,
            "新浪财经": fetch_sina_finance,
            "华尔街见闻": fetch_wallstreetcn,
            "新浪科技RSS": fetch_rss_sina_tech,
            "网易科技RSS": fetch_rss_163_tech,
            "虎嗅RSS": fetch_rss_huxiu,
            "腾讯科技": fetch_tencent_tech,
            "IT之家": fetch_it_home,
            "财联社": fetch_cls,
            "36氪": fetch_36kr,
        }

        all_news = []
        source_counts = {}
        print("\n--- 开始采集新闻 ---")
        for src in self.sources:
            func = source_functions.get(src)
            if not func:
                continue
            print(f"采集 {src} ...")
            try:
                if src == "AKShare":
                    news = func(['000977','002230','300750','688981'])
                else:
                    news = func()
                all_news.extend(news)
                source_counts[src] = len(news)
                print(f"  -> {len(news)} 条")
            except Exception as e:
                print(f"  -> 失败: {e}")
                source_counts[src] = 0

        print(f"\n原始采集总数: {len(all_news)} 条")
        for src, cnt in source_counts.items():
            if cnt > 0:
                print(f"  {src}: {cnt}")

        if not all_news:
            print("无任何采集数据，使用保底模拟数据")
            return self._get_fallback_news()

        # 筛选科技新闻
        print("\n--- 筛选科技新闻 ---")
        final_news = []
        for idx, item in enumerate(all_news):
            if DEBUG_MODE and idx % 10 == 0:
                print(f"  筛选进度: {idx+1}/{len(all_news)}")
            is_tech, cat, sent = deepseek_classify(item['title'], item.get('content', ''))
            if is_tech:
                uid = hashlib.md5(f"{item['title']}{item.get('source','')}".encode()).hexdigest()[:16]
                final_news.append({
                    "id": uid,
                    "timestamp": item['timestamp'],
                    "source": item['source'],
                    "title": item['title'],
                    "content": item['content'],
                    "url": item['url'],
                    "stock_mentioned": [],
                    "is_fact": False,
                    "predictive_sentences": [],
                    "tech_category": cat,
                    "tech_sentiment": sent,
                    "prediction_score": 0.0,
                    "impact_score": 0.0
                })

        # 去重
        unique = []
        for n in final_news:
            if not any(is_similar(n['title'], u['title']) for u in unique):
                unique.append(n)

        # 保底
        if len(unique) < 5:
            print(f"⚠️ 最终科技新闻仅 {len(unique)} 条，补充模拟数据")
            fallback = self._get_fallback_news()
            exist_titles = {u['title'] for u in unique}
            for fb in fallback:
                if fb['title'] not in exist_titles:
                    unique.append(fb)
                    if len(unique) >= 5:
                        break

        print(f"\n=== 最终输出科技新闻: {len(unique)} 条 ===")
        src_dist = {}
        for n in unique:
            src_dist[n['source']] = src_dist.get(n['source'], 0) + 1
        for src, cnt in src_dist.items():
            print(f"  {src}: {cnt}")
        return unique

# ==================== 入口 ====================
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--mock', action='store_true', help='使用模拟数据')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    collector = TechNewsCollector(use_mock=args.mock)
    news_list = collector.collect()
    output = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "total": len(news_list),
        "news": news_list
    }
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ 保存至 {args.output}")

if __name__ == "__main__":
    main()