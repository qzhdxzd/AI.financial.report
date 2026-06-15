#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ModelScope 环境优化版科技新闻采集器 v4.2
- 输出格式适配 test_input.json（数组，含 stock_mentioned / predictions / is_fact）
- 自动提取预测性句子和股票代码
- 保留原有全部采集源及筛选逻辑
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

# ---------- 公司名称 -> 股票代码映射 ----------
COMPANY_STOCK_MAP = {
    "英伟达": "NVDA", "NVIDIA": "NVDA", "nvidia": "NVDA",
    "AMD": "AMD", "amd": "AMD",
    "英特尔": "INTC", "Intel": "INTC",
    "苹果": "AAPL", "Apple": "AAPL",
    "微软": "MSFT", "Microsoft": "MSFT",
    "谷歌": "GOOGL", "Google": "GOOGL", "Alphabet": "GOOGL",
    "特斯拉": "TSLA", "Tesla": "TSLA",
    "台积电": "TSM", "TSMC": "TSM",
    "中芯国际": "688981", "SMIC": "688981",
    "阿里巴巴": "BABA", "Alibaba": "BABA",
    "腾讯": "TCEHY", "Tencent": "TCEHY",
    "百度": "BIDU", "Baidu": "BIDU",
    "宁德时代": "300750", "CATL": "300750",
    "比亚迪": "002594", "BYD": "002594",
    "华为": "未上市",
    "高通": "QCOM", "Qualcomm": "QCOM",
    "美光": "MU", "Micron": "MU",
    "阿斯麦": "ASML", "ASML": "ASML",
    "OpenAI": "未上市",
    "Meta": "META", "Facebook": "META",
    "亚马逊": "AMZN", "Amazon": "AMZN",
}
COMMON_STOCK_PATTERN = re.compile(r'\b([A-Z]{2,5})\b')
A_STOCK_PATTERN = re.compile(r'\b([0-9]{6})\b')

# 预测关键词
PREDICTION_KEYWORDS = [
    "预计", "可能", "或将", "有望", "预期", "预测", "或成为",
    "将会", "即将", "或达", "或超", "或提升", "或下降", "或加速",
    "或放缓", "或引发", "或带动", "可能带动", "可能影响", "可能推动"
]

# ---------- 保底模拟新闻（已适配新格式）----------
FALLBACK_NEWS = [
    {
        "title": "英伟达发布新一代AI芯片H200，算力提升3倍",
        "content": "英伟达今日宣布推出新一代AI加速卡H200，预计将带动全球AI算力需求大幅增长。",
        "source": "模拟数据",
        "stock_mentioned": ["NVDA"],
        "is_fact": False,
        "predictions": ["预计将带动全球AI算力需求大幅增长"]
    },
    {
        "title": "中芯国际季度营收超预期，半导体行业回暖",
        "content": "中芯国际公告显示，三季度营收同比增长34%，超出市场预期，行业景气度回升。",
        "source": "模拟数据",
        "stock_mentioned": ["688981"],
        "is_fact": True,
        "predictions": []
    },
    {
        "title": "工信部：加快推动人工智能与实体经济深度融合",
        "content": "工信部相关负责人表示，下一步将出台更多政策支持AI产业发展，推动大模型在工业场景落地。",
        "source": "模拟数据",
        "stock_mentioned": [],
        "is_fact": True,
        "predictions": []
    }
]

# ---------- 工具函数 ----------
def is_similar(t1: str, t2: str, thresh: float = 0.6) -> bool:
    return SequenceMatcher(None, t1, t2).ratio() > thresh

def clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()

def format_timestamp(ts: any) -> str:
    """统一转为 '%Y-%m-%d %H:%M:%S'"""
    if not ts:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if isinstance(ts, str):
            if 'T' in ts:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        elif isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
        else:
            dt = datetime.now()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def extract_stock_mentioned(text: str, title: str = "") -> List[str]:
    """从文本中提取股票代码（基于映射表 + 常见模式）"""
    combined = f"{title} {text}".lower()
    mentioned = set()
    # 公司名称映射
    for company, code in COMPANY_STOCK_MAP.items():
        if company.lower() in combined and code != "未上市":
            mentioned.add(code)
    # 美股模式
    upper_text = f"{title} {text}"
    for match in COMMON_STOCK_PATTERN.finditer(upper_text):
        code = match.group(1)
        if code not in {"THE", "AND", "FOR", "NOT", "BUT", "ARE", "WAS", "CAN", "HOW", "WHY", "ALL", "ANY"}:
            mentioned.add(code)
    # A股6位数字
    for match in A_STOCK_PATTERN.finditer(combined):
        mentioned.add(match.group(1))
    return list(mentioned)

def extract_predictions(text: str) -> List[str]:
    """提取包含预测关键词的句子"""
    if not text:
        return []
    sentences = re.split(r'[。；!?；\n]', text)
    preds = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if any(kw in sent for kw in PREDICTION_KEYWORDS):
            if sent not in preds and len(sent) < 150:
                preds.append(sent)
    return preds

def convert_to_input_format(item: Dict) -> Dict:
    """将内部新闻条目转换为 test_input.json 所需格式"""
    title = clean_text(item.get('title', '无标题'))
    content = clean_text(item.get('content', ''))
    full_text = f"{title} {content}"
    predictions = extract_predictions(full_text)
    stock_mentioned = extract_stock_mentioned(full_text, title)
    is_fact = len(predictions) == 0
    return {
        "id": item.get('id', hashlib.md5(f"{title}{item.get('source','')}".encode()).hexdigest()[:16]),
        "timestamp": format_timestamp(item.get('timestamp')),
        "source": item.get('source', '未知'),
        "title": title,
        "content": content if content else title,
        "stock_mentioned": stock_mentioned,
        "is_fact": is_fact,
        "predictions": predictions
    }

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

# ---------- DeepSeek 相关函数（与原始保持一致）----------
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
    NON_TECH_INDICATORS = [
        "娱乐", "明星", "影视", "电视剧", "电影", "综艺", "八卦", "绯闻",
        "体育", "足球", "篮球", "NBA", "世界杯", "奥运会", "田径", "游泳",
        "美食", "旅游", "酒店", "时尚", "美妆", "穿搭",
        "汽车评测", "房产", "家居", "装修", "教育政策", "考试", "留学",
        "育儿", "健康", "养生", "医疗", "疫情", "疫苗", "中医",
        "天气", "交通管制", "限行", "菜价", "油价",
    ]
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
        NON_TECH_INDICATORS = ["娱乐", "明星", "影视", "体育", "美食", "旅游", "房产", "教育", "育儿", "健康", "天气"]
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
    try:
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
    news = []
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

    def _get_fallback_news(self) -> List[Dict]:
        now = format_timestamp(datetime.now())
        result = []
        for idx, item in enumerate(FALLBACK_NEWS):
            result.append({
                "id": f"fallback_{idx}",
                "timestamp": now,
                "source": item["source"],
                "title": item["title"],
                "content": item["content"],
                "stock_mentioned": item.get("stock_mentioned", []),
                "is_fact": item.get("is_fact", True),
                "predictions": item.get("predictions", [])
            })
        return result

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

        # 筛选科技新闻（本地关键词 + DeepSeek 双保险）
        print("\n--- 筛选科技新闻 ---")
        tech_news = []
        for idx, item in enumerate(all_news):
            if DEBUG_MODE and idx % 10 == 0:
                print(f"  筛选进度: {idx+1}/{len(all_news)}")
            # 先用本地关键词分类（作为保底）
            is_tech_local, cat_local, sent_local = local_classify(item['title'], item.get('content', ''))
            # 再用 DeepSeek 分类（如果有 API Key）
            is_tech_ds, cat_ds, sent_ds = deepseek_classify(item['title'], item.get('content', ''))
            # 任一判定为科技即保留（本地关键词优先，DeepSeek 补充）
            is_tech = is_tech_local or is_tech_ds
            cat = cat_local if is_tech_local else cat_ds
            sent = sent_local if is_tech_local else sent_ds
            if is_tech:
                uid = hashlib.md5(f"{item['title']}{item.get('source','')}".encode()).hexdigest()[:16]
                tech_news.append({
                    "id": uid,
                    "timestamp": item.get('timestamp', datetime.now()),
                    "source": item.get('source', '未知'),
                    "title": item['title'],
                    "content": item.get('content', ''),
                    "url": item.get('url', ''),
                    "tech_category": cat,
                    "tech_sentiment": sent,
                })

        # 去重
        unique = []
        for n in tech_news:
            if not any(is_similar(n['title'], u['title']) for u in unique):
                unique.append(n)

        # 保底数量
        if len(unique) < 5:
            print(f"⚠️ 最终科技新闻仅 {len(unique)} 条，补充模拟数据")
            fallback = self._get_fallback_news()
            exist_titles = {u['title'] for u in unique}
            for fb in fallback:
                if fb['title'] not in exist_titles:
                    unique.append({
                        "id": fb['id'],
                        "timestamp": fb['timestamp'],
                        "source": fb['source'],
                        "title": fb['title'],
                        "content": fb['content'],
                        "url": "",
                        "tech_category": "科技",
                        "tech_sentiment": "neutral",
                    })
                    if len(unique) >= 5:
                        break

        # 转换为最终 input 格式
        final_list = [convert_to_input_format(item) for item in unique]

        print(f"\n=== 最终输出科技新闻: {len(final_list)} 条 ===")
        src_dist = {}
        for n in final_list:
            src_dist[n['source']] = src_dist.get(n['source'], 0) + 1
        for src, cnt in src_dist.items():
            print(f"  {src}: {cnt}")
        return final_list

# ==================== 入口 ====================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="科技新闻采集器，输出格式为 test_input.json 数组")
    parser.add_argument('--output', '-o', default='data/news.json', help="输出 JSON 文件路径（数组格式）")
    parser.add_argument('--mock', action='store_true', help='使用模拟数据')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    collector = TechNewsCollector(use_mock=args.mock)
    news_list = collector.collect()
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成 {len(news_list)} 条新闻，保存至 {args.output}")

if __name__ == "__main__":
    main()