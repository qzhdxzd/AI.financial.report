#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化版科技新闻采集器 (v2.0)
改进点：
1. 增加本地关键词回退，DeepSeek 不可用时仍能筛选
2. 修复财联社、36氪等源 0 数据问题，使用公开API
3. 新增 RSS 源（新浪科技、网易科技、虎嗅）提高稳定性
4. 使用 Session 保持连接，增强反爬能力
5. 更详细的日志与数据统计
"""

import json
import os
import hashlib
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from difflib import SequenceMatcher
import requests
from bs4 import BeautifulSoup

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

# 环境变量
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 保底模拟新闻
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

# ==================== 本地关键词过滤器（DeepSeek不可用时的回退） ====================
TECH_KEYWORDS = [
    # 核心技术领域
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
    # 产品/公司（常与科技相关）
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

def local_classify(title: str, content: str) -> tuple:
    """
    本地规则判断是否科技新闻，返回 (is_tech, category, sentiment)
    """
    text = f"{title} {content}".lower()
    
    # 先检查非科技排除词
    for w in NON_TECH_INDICATORS:
        if w in text:
            return (False, "非科技", "neutral")
    
    # 检查科技关键词
    matched_cat = "科技"
    for kw in TECH_KEYWORDS:
        if kw.lower() in text:
            matched_cat = kw
            break
    else:
        # 没有关键词命中，但也没有非科技词，保守归为非科技
        return (False, "非科技", "neutral")
    
    # 简单情感判断
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


# ==================== 辅助函数 ====================
def is_similar(t1, t2, thresh=0.6):
    return SequenceMatcher(None, t1, t2).ratio() > thresh

def clean_text(text):
    return re.sub(r'\s+', ' ', text or '').strip()

# 全局 session，复用连接
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
})

def safe_request(url, timeout=15, headers=None, retries=2):
    """带重试的请求，使用全局 session"""
    if headers:
        session.headers.update(headers)
    for i in range(retries):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(1)
    return None

def call_deepseek(prompt: str, max_tokens=80) -> Optional[str]:
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

def deepseek_classify(title: str, content: str):
    """优先使用 DeepSeek 分类，失败时回退到本地规则"""
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
        # 二次验证非科技词
        full_text = f"{title} {content}".lower()
        if not is_tech and any(indicator in full_text for indicator in NON_TECH_INDICATORS):
            return (False, "非科技", "neutral")
        return (is_tech, data.get("category", "科技"), data.get("sentiment", "neutral"))
    except Exception:
        return local_classify(title, content)

def deepseek_summarize(content: str) -> str:
    """生成摘要，失败则截取"""
    if not content or len(content.strip()) < 10:
        return "内容较短，无详细内容。"
    
    if DEEPSEEK_API_KEY:
        prompt = f"""请对以下新闻内容生成一个简洁准确的概览，限制在100字以内，突出关键信息和技术要点：
内容：{content[:500]}"""
        result = call_deepseek(prompt, max_tokens=100)
        if result:
            result = result.replace('"', '').replace("'", "").strip()
            return result
    
    # 回退：直接截取
    return content[:100] + "..." if len(content) > 100 else content


# ==================== 数据源采集函数 ====================

# ---------- 原有源（已优化） ----------
def fetch_akshare(stocks):
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

def fetch_tushare():
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

def fetch_eastmoney():
    try:
        url = "https://finance.eastmoney.com/ajax/RefreshListPageAjax.aspx?cb=callback&param=type%3A%221112%22%2Cpageindex%3A1%2Cpagesize%3A20%2Cftime%3A%22%22%2Cfenum%3A%22%22%2Cfield%3A%22%22%2Corder%3A%22desc%22%2Ctabid%3A%22%22%2Cfattr%3A%22%22%2Cftype%3A%22%22%2Ctag%3A%22%22%2Csort%3A%22%22%2Cdate%3A%22%22"
        resp = safe_request(url)
        if not resp:
            return []
        json_match = re.search(r'callback\((.*)\)', resp.text)
        if not json_match:
            return []
        data = json.loads(json_match.group(1))
        news = []
        for item in data.get('re', {}).get('list', [])[:10]:
            title = clean_text(item.get('title', ''))
            raw_summary = clean_text(item.get('summary', ''))
            content = deepseek_summarize(raw_summary)
            news.append({
                "title": title,
                "content": content,
                "timestamp": item.get('ptime', datetime.now().isoformat()),
                "source": "东方财富",
                "url": item.get('url', '')
            })
        return news
    except Exception as e:
        print(f"   东方财富失败: {e}")
        return []

def fetch_sina_finance():
    try:
        resp = safe_request("https://api.finance.sina.com.cn/cbkx/roll.d.json?size=20&page=1")
        if not resp:
            return []
        data = resp.json()
        news = []
        for item in data.get('result', {}).get('data', [])[:15]:
            title = clean_text(item.get('title', ''))
            raw_intro = clean_text(item.get('intro', ''))
            content = deepseek_summarize(raw_intro)
            news.append({
                "title": title,
                "content": content,
                "timestamp": item.get('ctime', datetime.now().isoformat()),
                "source": "新浪财经",
                "url": item.get('url', '')
            })
        return news
    except Exception as e:
        print(f"   新浪财经失败: {e}")
        return []

def fetch_wallstreetcn():
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

def fetch_tencent_tech():
    try:
        resp = safe_request("https://tech.qq.com/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.Q-tpWrap h3 a, .list-hd h3 a')
        news = []
        for a in items[:15]:
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

def fetch_ifeng_tech():
    try:
        resp = safe_request("http://tech.ifeng.com/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.news-stream-newsStream .stream-headline-title a')
        news = []
        for a in items[:15]:
            title = clean_text(a.get_text())
            if title and len(title) > 5:
                content = deepseek_summarize(title)
                news.append({
                    "title": title,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "source": "凤凰科技",
                    "url": a.get('href', '')
                })
        return news
    except Exception as e:
        print(f"   凤凰科技失败: {e}")
        return []

def fetch_it_home():
    try:
        resp = safe_request("https://www.ithome.com/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.bx ul li a')
        news = []
        for a in items[:15]:
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

def fetch_cn_beta():
    try:
        resp = safe_request("https://www.cnbeta.com/")
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.items-area .item .title a')
        news = []
        for a in items[:15]:
            title = clean_text(a.get_text())
            if title and len(title) > 5:
                content = deepseek_summarize(title)
                news.append({
                    "title": title,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "source": "cnBeta",
                    "url": a.get('href', '')
                })
        return news
    except Exception as e:
        print(f"   cnBeta失败: {e}")
        return []

# ---------- 修复的源 ----------
def fetch_cls():
    """财联社电报 - 使用公开接口"""
    url = "https://www.cls.cn/api/telegraph/list?rn=30"
    headers = {
        "Referer": "https://www.cls.cn/telegraph",
        "Accept": "application/json"
    }
    try:
        resp = safe_request(url, headers=headers)
        if not resp:
            return []
        data = resp.json()
        items = data.get("data", {}).get("roll_data", [])
        news = []
        for item in items:
            title = clean_text(item.get("title") or item.get("content", ""))
            content = deepseek_summarize(title)
            news.append({
                "title": title,
                "content": content,
                "timestamp": item.get("ctime", datetime.now().isoformat()),
                "source": "财联社",
                "url": item.get("shareurl") or f"https://www.cls.cn/detail/{item.get('id')}"
            })
        return news
    except Exception as e:
        print(f"   财联社失败: {e}")
        return []

def fetch_36kr():
    """36氪 - 修复接口参数"""
    try:
        headers = {
            "Referer": "https://36kr.com/",
            "Accept": "application/json"
        }
        resp = safe_request("https://36kr.com/api/information-flow/article/latest?per_page=20", headers=headers)
        if not resp:
            return []
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        news = []
        for item in items:
            title = clean_text(item.get("title") or item.get("item_title", ""))
            summary = clean_text(item.get("summary") or item.get("item_summary", ""))
            content = deepseek_summarize(summary) if summary else deepseek_summarize(title)
            news.append({
                "title": title,
                "content": content,
                "timestamp": item.get("published_at") or item.get("created_at", datetime.now().isoformat()),
                "source": "36氪",
                "url": item.get("url") or f"https://36kr.com/p/{item.get('id')}"
            })
        return news
    except Exception as e:
        print(f"   36氪失败: {e}")
        return []

# ---------- 新增 RSS 源 ----------
def fetch_rss_sina_tech():
    """新浪科技 RSS"""
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

def fetch_rss_163_tech():
    """网易科技 RSS"""
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

def fetch_rss_huxiu():
    """虎嗅 RSS"""
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


# ==================== 主采集器 ====================
class TechNewsCollector:
    def __init__(self, use_mock=False, use_llm_filter=True, selected_sources=None):
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter and bool(DEEPSEEK_API_KEY)  # 无key时自动降级
        self.sources = selected_sources or [
            "AKShare", "Tushare", "东方财富", "新浪财经",
            "财联社", "华尔街见闻", "36氪",
            "腾讯科技", "凤凰科技", "IT之家", "cnBeta",
            "新浪科技RSS", "网易科技RSS", "虎嗅RSS"
        ]
        if not DEEPSEEK_API_KEY:
            print("⚠️ 未设置 DEEPSEEK_API_KEY，将使用本地关键词过滤（准确性降低）")
        else:
            print("✓ DeepSeek API 已配置，使用 AI 筛选")

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

    def collect(self):
        if self.use_mock:
            print("使用模拟数据模式")
            return self._get_fallback_news()

        # 1. 多源采集
        source_functions = {
            "AKShare": fetch_akshare,
            "Tushare": fetch_tushare,
            "东方财富": fetch_eastmoney,
            "新浪财经": fetch_sina_finance,
            "财联社": fetch_cls,
            "华尔街见闻": fetch_wallstreetcn,
            "36氪": fetch_36kr,
            "腾讯科技": fetch_tencent_tech,
            "凤凰科技": fetch_ifeng_tech,
            "IT之家": fetch_it_home,
            "cnBeta": fetch_cn_beta,
            "新浪科技RSS": fetch_rss_sina_tech,
            "网易科技RSS": fetch_rss_163_tech,
            "虎嗅RSS": fetch_rss_huxiu,
        }

        all_news = []
        source_counts = {}
        print("\n--- 开始采集新闻 ---")
        for src in self.sources:
            if src not in source_functions:
                continue
            print(f"采集 {src} ...")
            try:
                if src == "AKShare":
                    news = source_functions[src](['000977','002230','300750','688981'])
                else:
                    news = source_functions[src]()
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

        # 2. 科技新闻筛选
        print("\n--- 筛选科技新闻 ---")
        final_news = []
        for idx, item in enumerate(all_news):
            print(f"筛选 {idx+1}/{len(all_news)}: {item['title'][:30]}...")
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
            else:
                print(f"   -> 非科技，跳过")

        # 3. 去重
        unique = []
        for n in final_news:
            similar_found = False
            for u in unique:
                if is_similar(n['title'], u['title'], thresh=0.6):
                    similar_found = True
                    break
            if not similar_found:
                unique.append(n)

        # 4. 保底机制：少于5条时补充模拟数据
        if len(unique) < 5:
            print(f"\n⚠️ 最终科技新闻仅 {len(unique)} 条，自动补充模拟数据")
            fallback = self._get_fallback_news()
            existing_titles = {u['title'] for u in unique}
            for fb in fallback:
                if fb['title'] not in existing_titles:
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


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--mock', action='store_true', help='使用模拟数据（完全跳过在线采集）')
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