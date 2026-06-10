#!/usr/bin/env python3
import json
import os
import hashlib
import re
import time
from datetime import datetime
from typing import List, Dict
from difflib import SequenceMatcher
import requests
from bs4 import BeautifulSoup

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 预设高质量模拟新闻（最终保底 + 演示模式）
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

# ==================== 辅助函数 ====================
def is_similar(t1, t2, thresh=0.6):
    return SequenceMatcher(None, t1, t2).ratio() > thresh

def clean_text(text):
    return re.sub(r'\s+', ' ', text or '').strip()

def call_deepseek(prompt: str, max_tokens=80):
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
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        pass
    return None

def deepseek_classify(title: str, content: str):
    """返回 (is_tech, category, sentiment)"""
    # 本地预过滤：检查明显的非科技关键词，减少不必要的API调用
    non_tech_indicators = ["娱乐", "明星", "影视", "体育", "足球", "篮球", "综艺", "八卦", "美食", "旅游", "时尚", "美妆", "汽车", "房产", "家居", "教育", "考试", "留学", "育儿", "健康", "养生", "医疗", "疫情", "疫苗"]
    full_text_lower = f"{title} {content}".lower()
    
    # 如果包含明显的非科技词汇，且不包含强烈的科技词汇，直接判定为非科技
    tech_indicators = ["ai", "芯片", "半导体", "互联网", "软件", "硬件", "算法", "数据", "网络", "智能", "科技", "digital", "tech", "computer", "software", "hardware"]
    has_non_tech = any(indicator in full_text_lower for indicator in non_tech_indicators)
    has_tech = any(indicator in full_text_lower for indicator in tech_indicators)
    
    if has_non_tech and not has_tech:
        return (False, "非科技", "neutral")

    prompt = f"""请仔细判断以下新闻是否属于科技领域。
科技新闻主要包括：AI、人工智能、机器学习、深度学习、芯片、半导体、集成电路、计算机、软件、硬件、互联网、移动互联网、大数据、云计算、物联网、5G、6G、区块链、虚拟现实、增强现实、自动驾驶、机器人、新能源车、生物技术、金融科技、通讯技术、网络安全、游戏技术、数码产品、科技公司动态等。
非科技新闻包括：纯娱乐八卦、体育赛事、普通社会新闻、传统行业（如餐饮、服装、房地产销售等）除非有显著的技术创新背景。

如果是科技领域新闻，返回JSON: {{"is_tech": true, "category": "具体科技领域(如AI,半导体,互联网等)", "sentiment": "positive/negative/neutral"}}
如果不是科技领域新闻，返回JSON: {{"is_tech": false, "category": "非科技", "sentiment": "neutral"}}

标题：{title}
内容摘要：{content[:300]}"""
    
    result = call_deepseek(prompt)
    if not result:
        # 如果API调用失败，根据本地关键词简单判断
        if has_tech:
            return (True, "科技", "neutral")
        return (False, "非科技", "neutral")
    
    try:
        data = json.loads(result)
        is_tech = data.get("is_tech", False)
        category = data.get("category", "通用")
        sentiment = data.get("sentiment", "neutral")
        
        if not is_tech or category == "非科技":
            return (False, "非科技", "neutral")
            
        return (is_tech, category, sentiment)
    except Exception:
        if has_tech:
            return (True, "科技", "neutral")
        return (False, "非科技", "neutral")

# ==================== 数据源采集 ====================
def fetch_akshare(stocks):
    if not AKSHARE_AVAILABLE:
        return []
    news = []
    for code in stocks:
        try:
            df = ak.stock_news_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    news.append({
                        "title": clean_text(row.get('title', '')),
                        "content": clean_text(row.get('content', ''))[:500],
                        "timestamp": row.get('publish_time', datetime.now().isoformat()),
                        "source": "AKShare",
                        "url": row.get('url', '')
                    })
            time.sleep(0.3)
        except:
            pass
    return news

def fetch_cls():
    url = "https://www.cls.cn/telegraph"
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        # 尝试多种选择器以适配网站结构变化
        items = soup.select('.telegraph-item .content') 
        if not items:
            items = soup.select('.dibu-content a')
        if not items:
            items = soup.select('.title a')
            
        news_list = []
        for item in items[:30]:
            # 处理不同结构的内容提取
            if item.name == 'div': # .telegraph-item .content
                 title_tag = item.select_one('a') or item.select_one('div')
                 title = clean_text(title_tag.get_text()) if title_tag else clean_text(item.get_text())
                 link_tag = item.select_one('a')
                 link = link_tag['href'] if link_tag and link_tag.get('href') else ''
            else: # a tag directly
                title = clean_text(item.get_text())
                link = item.get('href', '')

            if title and len(title) > 5:
                if link and 'http' not in link:
                    link = 'https://www.cls.cn' + link
                news_list.append({
                    "title": title,
                    "content": "",
                    "timestamp": datetime.now().isoformat(),
                    "source": "财联社",
                    "url": link
                })
        return news_list
    except Exception as e:
        print(f"财联社数据获取失败: {e}")
        return []

def fetch_wallstreetcn():
    # 尝试多个API端点和网页源
    sources = [
        ("https://api-prod.wallstreetcn.com/apiv1/content/lives?channel=global&limit=30", "华尔街见闻"),
        ("https://api-app-wallstreetcn-com-apifc.wallstcn.com/apiv1/content/lives?channel=global&limit=30", "华尔街见闻"),
    ]
    
    for api_url, source_name in sources:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
            }
            response = requests.get(api_url, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                news_items = [{
                    "title": clean_text(item.get('content_text', '')[:100]),
                    "content": clean_text(item.get('content_text', '')),
                    "timestamp": item.get('created_at', datetime.now().isoformat()),
                    "source": source_name,
                    "url": f"https://wallstreetcn.com/live/{item.get('id','')}" if item.get('id') else ''
                } for item in data.get('data', {}).get('items', []) if item.get('content_text')]
                if news_items:
                    return news_items
        except Exception as e:
            print(f"{source_name} API获取失败: {e}")
    
    # 如果API都失败，尝试网页爬取
    try:
        web_url = "https://www.wallstreetcn.com/live/global"
        response = requests.get(web_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        })
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.live-list-item .title a')  # 调整选择器
        if not items:
            items = soup.select('.article-item .title a')  # 备用选择器
        if not items:
            items = soup.select('article a')  # 再备用选择器
        web_news = [{
            "title": clean_text(item.get_text()),
            "content": clean_text(item.get_text()),
            "timestamp": datetime.now().isoformat(),
            "source": "华尔街见闻",
            "url": item.get('href', '') if item.get('href') else ''
        } for item in items[:20] if item.get_text().strip()]
        return web_news
    except Exception as e:
        print(f"华尔街见闻网页爬取失败: {e}")
        return []

def fetch_sina_tech():
    """获取新浪科技新闻"""
    urls = [
        "https://tech.sina.com.cn/it/",
        "https://tech.sina.com.cn/internet/",
        "https://tech.sina.com.cn/electron/",
    ]
    
    for url in urls:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = requests.get(url, timeout=10, headers=headers)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            news_items = []
            # 选择内部链接，通常包含新闻
            for item in soup.select('a[href*=".shtml"]'):
                title = clean_text(item.get_text())
                link = item.get('href', '')
                if title and len(title) > 5:
                    full_link = link if link.startswith('http') else 'https:' + link if link.startswith('//') else 'https://tech.sina.com.cn' + link
                    news_items.append({
                        "title": title,
                        "content": "",
                        "timestamp": datetime.now().isoformat(),
                        "source": "新浪科技",
                        "url": full_link
                    })
            if news_items:
                return news_items[:20]
        except Exception as e:
            print(f"新浪科技数据获取失败: {e}")
    
    return []

def fetch_36kr():
    """获取36氪科技新闻"""
    try:
        url = "https://36kr.com/api/information-flow/article/latest?per_page=20"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://36kr.com/",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        response = requests.get(url, timeout=15, headers=headers)
        data = response.json()
        return [{
            "title": clean_text(item['item_title']),
            "content": clean_text(item.get('summary', '')),
            "timestamp": item.get('published_at', datetime.now().isoformat()),
            "source": "36氪",
            "url": f"https://36kr.com/p/{item['id']}"
        } for item in data.get('data', {}).get('items', []) if item.get('item_title')]
    except Exception as e:
        print(f"36氪数据获取失败: {e}")
        return []

def fetch_zhihu_daily():
    """获取知乎热榜科技类文章"""
    try:
        # 尝试获取知乎热榜中科技相关的内容
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("https://www.zhihu.com/api/v3/feed/topstory/hot-list?limit=20", timeout=10, headers=headers)
        data = response.json()
        tech_related = []
        tech_keywords = ['科技', 'AI', '人工智能', '芯片', '互联网', '软件', '硬件', '手机', '电脑', '编程', '算法', '数据', '网络', '智能']
        for item in data.get('data', []):
            target = item.get('target', {})
            title = clean_text(target.get('title', ''))
            content = clean_text(target.get('excerpt', ''))
            # 检查是否与科技相关
            full_text = f"{title} {content}".lower()
            if any(keyword.lower() in full_text for keyword in tech_keywords):
                question_id = target.get('question', {}).get('id', '')
                tech_related.append({
                    "title": title,
                    "content": content if content else title,
                    "timestamp": datetime.now().isoformat(),
                    "source": "知乎热榜",
                    "url": f"https://zhihu.com/question/{question_id}" if question_id else ''
                })
        return tech_related
    except Exception as e:
        print(f"知乎热榜数据获取失败: {e}")
        return []

def fetch_tencent_tech():
    """获取腾讯科技新闻"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        }
        response = requests.get("https://tech.qq.com/", timeout=15, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        
        # 尝试多种选择器
        selectors = [
            '.Q-tpWrap h3 a',
            '.list-hd h3 a',
            '.info h3 a',
            '.tit a',
            '.newspic-news h3 a'
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            for item in elements:
                title = clean_text(item.get_text())
                link = item.get('href', '')
                if title and link:
                    full_link = link if link.startswith('http') else 'https://tech.qq.com' + link
                    items.append({
                        "title": title,
                        "content": "",
                        "timestamp": datetime.now().isoformat(),
                        "source": "腾讯科技",
                        "url": full_link
                    })
            if len(items) >= 10:  # 如果已经有足够新闻，就跳出
                break
        return items[:15]
    except Exception as e:
        print(f"腾讯科技数据获取失败: {e}")
        return []

def fetch_ifeng_tech():
    """获取凤凰科技新闻"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        }
        response = requests.get("http://tech.ifeng.com/", timeout=15, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        
        # 尝试多种选择器
        selectors = [
            '.newsList2018 .news-stream-newsStream .stream-headline-title a',
            '.item .h5 a',
            '.largeImgNewsCls a',
            '.newsMain .item .h5 a'
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            for item in elements:
                title = clean_text(item.get_text())
                link = item.get('href', '')
                if title and link:
                    items.append({
                        "title": title,
                        "content": "",
                        "timestamp": datetime.now().isoformat(),
                        "source": "凤凰科技",
                        "url": link
                    })
            if len(items) >= 10:  # 如果已经有足够新闻，就跳出
                break
        return items[:15]
    except Exception as e:
        print(f"凤凰科技数据获取失败: {e}")
        return []

def fetch_baidu_top():
    """获取百度搜索风云榜科技类"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        }
        response = requests.get("http://top.baidu.com/buzz?b=11", timeout=15, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        
        for item in soup.select('.keyword a.list-title')[:10]:
            title = clean_text(item.get_text())
            if title:
                items.append({
                    "title": title,
                    "content": "百度热搜科技新闻",
                    "timestamp": datetime.now().isoformat(),
                    "source": "百度热搜",
                    "url": item.get('href', '')
                })
        return items
    except Exception as e:
        print(f"百度热搜数据获取失败: {e}")
        return []

def fetch_huxiu():
    """获取虎嗅网科技新闻"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("https://www.huxiu.com/", timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        # 虎嗅网首页文章列表
        for item in soup.select('.article-item .transition a')[:15]:
            title = clean_text(item.get_text())
            link = item.get('href', '')
            if title and link and len(title) > 5:
                full_link = f"https://www.huxiu.com{link}" if link.startswith('/') else link
                items.append({
                    "title": title,
                    "content": "",
                    "timestamp": datetime.now().isoformat(),
                    "source": "虎嗅网",
                    "url": full_link
                })
        return items
    except Exception as e:
        print(f"虎嗅网数据获取失败: {e}")
        return []

def fetch_it_home():
    """获取IT之家新闻"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("https://www.ithome.com/", timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        # IT之首页面新闻列表
        for item in soup.select('.bx ul li a')[:15]:
            title = clean_text(item.get_text())
            link = item.get('href', '')
            if title and link and len(title) > 5:
                full_link = link if link.startswith('http') else 'https://www.ithome.com' + link
                items.append({
                    "title": title,
                    "content": "",
                    "timestamp": datetime.now().isoformat(),
                    "source": "IT之家",
                    "url": full_link
                })
        return items
    except Exception as e:
        print(f"IT之家数据获取失败: {e}")
        return []

def fetch_cn_beta():
    """获取 cnBeta 新闻"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("https://www.cnbeta.com/", timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        # cnBeta 首页新闻列表
        for item in soup.select('.items-area .item .title a')[:15]:
            title = clean_text(item.get_text())
            link = item.get('href', '')
            if title and link and len(title) > 5:
                full_link = link if link.startswith('http') else 'https://www.cnbeta.com' + link
                items.append({
                    "title": title,
                    "content": "",
                    "timestamp": datetime.now().isoformat(),
                    "source": "cnBeta",
                    "url": full_link
                })
        return items
    except Exception as e:
        print(f"cnBeta数据获取失败: {e}")
        return []

# ==================== 主采集器类 ====================
class TechNewsCollector:
    def __init__(self, use_mock=False, use_llm_filter=True, selected_sources=None):
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter
        self.sources = selected_sources or ["AKShare", "财联社", "华尔街见闻", "新浪科技", "36氪", "知乎热榜", "腾讯科技", "凤凰科技", "虎嗅网", "IT之家", "cnBeta"]

    def _get_fallback_news(self):
        """返回保底模拟新闻"""
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

        # 1. 多源采集 - 不进行任何预筛选
        all_news = []
        source_counts = {}
        
        source_functions = {
            "AKShare": fetch_akshare,
            "财联社": fetch_cls,
            "华尔街见闻": fetch_wallstreetcn,
            "新浪科技": fetch_sina_tech,
            "36氪": fetch_36kr,
            "知乎热榜": fetch_zhihu_daily,
            "腾讯科技": fetch_tencent_tech,
            "凤凰科技": fetch_ifeng_tech,
            "虎嗅网": fetch_huxiu,
            "IT之家": fetch_it_home,
            "cnBeta": fetch_cn_beta
        }
        
        for source_name in self.sources:
            if source_name in source_functions:
                print(f"正在采集{source_name}数据...")
                try:
                    if source_name == "AKShare":
                        # AKShare需要特殊参数
                        news = source_functions[source_name](['000977','002230','300750','688981'])
                    else:
                        news = source_functions[source_name]()
                    
                    all_news.extend(news)
                    source_counts[source_name] = len(news)
                    print(f"  - {source_name}: {len(news)} 条")
                except Exception as e:
                    print(f"  - {source_name}: 采集失败 - {e}")
                    source_counts[source_name] = 0

        print(f"原始采集: {len(all_news)} 条来自 {len([k for k, v in source_counts.items() if v > 0])} 个不同来源")
        for source, count in source_counts.items():
            if count > 0:
                print(f"  - {source}: {count} 条")

        if not all_news:
            print("无采集数据，使用保底模拟数据")
            return self._get_fallback_news()

        # 2. 使用改进的DeepSeek进行精确筛选
        print("使用 DeepSeek 进行科技新闻筛选...")
        final_news = []
        for idx, news in enumerate(all_news):
            print(f"DeepSeek 筛选进度: {idx+1}/{len(all_news)}")
            is_tech, cat, sent = deepseek_classify(news['title'], news.get('content', '')[:300])
            
            if is_tech:  # 只保留被DeepSeek判定为科技相关的新闻
                uid = hashlib.md5(f"{news['title']}{news.get('source','')}".encode()).hexdigest()[:16]
                final_news.append({
                    "id": uid,
                    "timestamp": news['timestamp'],
                    "source": news['source'],
                    "title": news['title'],
                    "content": news['content'][:500],
                    "url": news['url'],
                    "stock_mentioned": [],
                    "is_fact": False,
                    "predictive_sentences": [],
                    "tech_category": cat,
                    "tech_sentiment": sent,
                    "prediction_score": 0.0,
                    "impact_score": 0.0
                })
            else:
                print(f"  - 跳过非科技新闻: {news['title']} (分类: {cat})")

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

        print(f"最终科技新闻: {len(unique)} 条，来自 {len(set([n['source'] for n in unique]))} 个不同来源")
        for source in set([n['source'] for n in unique]):
            count = sum(1 for n in unique if n['source'] == source)
            print(f"  - {source}: {count} 条")
        
        # 如果最终新闻太少，补充一些fallback新闻
        if len(unique) < 5:
            print(f"最终新闻数量较少({len(unique)}条)，补充模拟新闻...")
            fallback_news = self._get_fallback_news()
            unique.extend(fallback_news[:min(5-len(unique), len(fallback_news))])
            print(f"补充后总数: {len(unique)} 条")

        return unique if unique else self._get_fallback_news()

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--mock', action='store_true')
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