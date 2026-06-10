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
    prompt = f"""请仔细判断以下新闻是否属于科技领域。科技新闻主要包括：AI、人工智能、机器学习、深度学习、芯片、半导体、集成电路、计算机、软件、硬件、互联网、移动互联网、大数据、云计算、物联网、5G、6G、区块链、虚拟现实、增强现实、自动驾驶、机器人、新能源车、生物技术、金融科技、通讯技术、网络安全、游戏技术等相关内容。

如果是科技领域新闻，返回: {{"is_tech": true, "category": "具体科技领域", "sentiment": "positive/negative/neutral"}}
如果不是科技领域新闻，返回: {{"is_tech": false, "category": "非科技领域", "sentiment": "neutral"}}

标题：{title}
内容：{content[:300]}"""
    result = call_deepseek(prompt)
    if not result:
        return (False, "非科技", "neutral")  # 如果API调用失败，默认认为不是科技新闻
    try:
        data = json.loads(result)
        is_tech = data.get("is_tech", False)
        # 进一步验证，如果标题或内容包含明显的非科技词汇，则不认为是科技新闻
        full_text = f"{title} {content}".lower()
        non_tech_indicators = ["娱乐", "明星", "影视", "体育", "足球", "篮球", "综艺", "八卦", "美食", "旅游", "时尚", "美妆", "汽车", "房产", "家居", "教育", "考试", "留学", "育儿", "健康", "养生", "医疗", "疫情", "疫苗"]
        if any(indicator in full_text for indicator in non_tech_indicators) and not is_tech:
            return (False, "非科技", "neutral")
        return (is_tech, data.get("category", "科技"), data.get("sentiment", "neutral"))
    except:
        return (False, "非科技", "neutral")

def deepseek_summarize(content: str) -> str:
    """使用DeepSeek生成内容概览"""
    if not content or len(content.strip()) < 10:
        return "内容较短，无详细内容。"
    
    prompt = f"""请对以下新闻内容生成一个简洁准确的概览，限制在100字以内，突出关键信息和技术要点：

内容：{content[:500]}"""
    
    result = call_deepseek(prompt, max_tokens=100)
    if result:
        # 清理可能的引号或多余字符
        result = result.replace('"', '').replace("'", "").strip()
        return result
    else:
        # 如果API调用失败，返回内容的前100个字符
        return content[:100] + "..." if len(content) > 100 else content

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
                    content_summary = deepseek_summarize(clean_text(row.get('content', '')))
                    news.append({
                        "title": clean_text(row.get('title', '')),
                        "content": content_summary,
                        "timestamp": row.get('publish_time', datetime.now().isoformat()),
                        "source": "AKShare",
                        "url": row.get('url', '')
                    })
            time.sleep(0.3)
        except:
            pass
    return news

def fetch_tushare():
    """获取Tushare财经新闻（如果没有安装tushare则跳过）"""
    try:
        import tushare as ts
        # 设置token（需要用户自行配置）
        token = os.environ.get("TUSHARE_TOKEN", "")
        if not token:
            print("Tushare token未配置，跳过Tushare数据获取")
            return []
        
        pro = ts.pro_api(token)
        # 获取新闻联播
        df = pro.cctv_news(date=datetime.now().strftime('%Y%m%d'))
        news = []
        for _, row in df.iterrows():
            content_summary = deepseek_summarize(clean_text(row.get('content', '')))
            news.append({
                "title": clean_text(row.get('title', '')),
                "content": content_summary,
                "timestamp": row.get('date', datetime.now().isoformat()),
                "source": "Tushare",
                "url": ""
            })
        return news
    except ImportError:
        print("Tushare未安装，跳过Tushare数据获取")
        return []
    except Exception as e:
        print(f"Tushare数据获取失败: {e}")
        return []

def fetch_eastmoney():
    """获取东方财富财经新闻"""
    try:
        url = "https://finance.eastmoney.com/ajax/RefreshListPageAjax.aspx?cb=callback&param=type%3A%221112%22%2Cpageindex%3A1%2Cpagesize%3A20%2Cftime%3A%22%22%2Cfenum%3A%22%22%2Cfield%3A%22%22%2Corder%3A%22desc%22%2Ctabid%3A%22%22%2Cfattr%3A%22%22%2Cftype%3A%22%22%2Ctag%3A%22%22%2Csort%3A%22%22%2Cdate%3A%22%22"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.eastmoney.com/"
        }
        response = requests.get(url, timeout=10, headers=headers)
        # 解析JSONP响应
        import re
        json_match = re.search(r'callback\((.*)\)', response.text)
        if json_match:
            data = json.loads(json_match.group(1))
            news = []
            for item in data.get('re', {}).get('list', [])[:10]:
                title = clean_text(item.get('title', ''))
                content_summary = deepseek_summarize(clean_text(item.get('summary', '')))
                news.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": item.get('ptime', datetime.now().isoformat()),
                    "source": "东方财富",
                    "url": item.get('url', '')
                })
            return news
    except Exception as e:
        print(f"东方财富数据获取失败: {e}")
        return []

def fetch_sina_finance():
    """获取新浪财经新闻"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/"
        }
        response = requests.get("https://api.finance.sina.com.cn/cbkx/roll.d.json?size=20&page=1", timeout=10, headers=headers)
        data = response.json()
        news = []
        for item in data.get('result', {}).get('data', [])[:15]:
            title = clean_text(item.get('title', ''))
            content_summary = deepseek_summarize(clean_text(item.get('intro', '')))
            news.append({
                "title": title,
                "content": content_summary,
                "timestamp": item.get('ctime', datetime.now().isoformat()),
                "source": "新浪财经",
                "url": item.get('url', '')
            })
        return news
    except Exception as e:
        print(f"新浪财经数据获取失败: {e}")
        return []

def fetch_cls():
    url = "https://www.cls.cn/telegraph"
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.telegraph-item .content')
        news_list = []
        for item in items[:30]:
            title_elem = item.select_one('a, div')
            if title_elem:
                title = clean_text(title_elem.get_text())
                content_summary = deepseek_summarize(clean_text(item.get_text()))
                news_list.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "财联社",
                    "url": title_elem.get('href', '') if title_elem.name == 'a' else ''
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
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            data = requests.get(api_url, headers=headers, timeout=10).json()
            news_items = []
            for item in data.get('data', {}).get('items', [])[:30]:
                if item.get('content_text'):
                    content_summary = deepseek_summarize(clean_text(item.get('content_text', '')))
                    news_items.append({
                        "title": clean_text(item.get('content_text', '')[:100]),
                        "content": content_summary,
                        "timestamp": item.get('created_at', datetime.now().isoformat()),
                        "source": source_name,
                        "url": f"https://wallstreetcn.com/live/{item.get('id','')}" if item.get('id') else ''
                    })
            if news_items:
                return news_items
        except Exception as e:
            print(f"{source_name} API获取失败: {e}")
    
    # 如果API都失败，尝试网页爬取
    try:
        web_url = "https://www.wallstreetcn.com/live/global"
        response = requests.get(web_url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.live-list-item .title a')  # 调整选择器
        if not items:
            items = soup.select('.article-item .title a')  # 备用选择器
        news_items = []
        for item in items[:20]:
            if item.get_text().strip():
                content_summary = deepseek_summarize(clean_text(item.get_text()))
                news_items.append({
                    "title": clean_text(item.get_text()),
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "华尔街见闻",
                    "url": item.get('href', '') if item.get('href') else ''
                })
        return news_items
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
            for item in soup.select('a[href*=".shtml"]')[:20]:  # 选择内部链接
                title = clean_text(item.get_text())
                if title and len(title) > 5:  # 确保标题有意义
                    content_summary = deepseek_summarize(title)  # 使用标题生成概览
                    news_items.append({
                        "title": title,
                        "content": content_summary,
                        "timestamp": datetime.now().isoformat(),
                        "source": "新浪科技",
                        "url": item.get('href', '') if item.get('href') else ''
                    })
            if news_items:
                return news_items
        except Exception as e:
            print(f"新浪科技数据获取失败: {e}")
    
    return []

def fetch_36kr():
    """获取36氪科技新闻"""
    try:
        url = "https://36kr.com/api/information-flow/article/latest?per_page=20"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://36kr.com/"
        }
        response = requests.get(url, timeout=10, headers=headers)
        data = response.json()
        news_items = []
        for item in data.get('data', {}).get('items', [])[:20]:
            if item.get('item_title'):
                content_summary = deepseek_summarize(clean_text(item.get('summary', '')))
                news_items.append({
                    "title": clean_text(item['item_title']),
                    "content": content_summary,
                    "timestamp": item.get('published_at', datetime.now().isoformat()),
                    "source": "36氪",
                    "url": f"https://36kr.com/p/{item['id']}"
                })
        return news_items
    except Exception as e:
        print(f"36氪数据获取失败: {e}")
        return []

def fetch_zhihu_daily():
    """获取知乎日报科技类文章"""
    try:
        # 尝试获取知乎热榜中科技相关的内容
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("https://www.zhihu.com/api/v3/feed/topstory/hot-list?limit=20", timeout=10, headers=headers)
        data = response.json()
        tech_related = []
        tech_keywords = ['科技', 'AI', '人工智能', '芯片', '互联网', '软件', '硬件', '手机', '电脑', '编程', '算法', '数据', '网络', '智能']
        for item in data.get('data', []):
            title = clean_text(item.get('target', {}).get('title', ''))
            content = clean_text(item.get('target', {}).get('excerpt', ''))
            # 检查是否与科技相关
            full_text = f"{title} {content}".lower()
            if any(keyword.lower() in full_text for keyword in tech_keywords):
                content_summary = deepseek_summarize(content)
                tech_related.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "知乎热榜",
                    "url": f"https://zhihu.com/question/{item.get('target', {}).get('question', {}).get('id', '')}"
                })
        return tech_related
    except Exception as e:
        print(f"知乎热榜数据获取失败: {e}")
        return []

def fetch_tencent_tech():
    """获取腾讯科技新闻"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("https://tech.qq.com/", timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        for item in soup.select('.Q-tpWrap h3 a, .list-hd h3 a')[:15]:
            title = clean_text(item.get_text())
            if title and len(title) > 5:
                content_summary = deepseek_summarize(title)
                items.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "腾讯科技",
                    "url": item.get('href', '')
                })
        return items
    except Exception as e:
        print(f"腾讯科技数据获取失败: {e}")
        return []

def fetch_ifeng_tech():
    """获取凤凰科技新闻"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("http://tech.ifeng.com/", timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        for item in soup.select('.newsList2018 .news-stream-newsStream .stream-headline-title a')[:15]:
            title = clean_text(item.get_text())
            if title and len(title) > 5:
                content_summary = deepseek_summarize(title)
                items.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "凤凰科技",
                    "url": item.get('href', '')
                })
        return items
    except Exception as e:
        print(f"凤凰科技数据获取失败: {e}")
        return []

def fetch_huxiu():
    """获取虎嗅网科技新闻"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("https://www.huxiu.com/", timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        for item in soup.select('.article-item .transition a')[:15]:
            title = clean_text(item.get_text())
            if title and len(title) > 5:
                content_summary = deepseek_summarize(title)
                items.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "虎嗅网",
                    "url": f"https://www.huxiu.com{item.get('href', '')}" if item.get('href', '').startswith('/') else item.get('href', '')
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
        for item in soup.select('.bx ul li a')[:15]:
            title = clean_text(item.get_text())
            if title and len(title) > 5:
                content_summary = deepseek_summarize(title)
                items.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "IT之家",
                    "url": item.get('href', '')
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
        for item in soup.select('.items-area .item .title a')[:15]:
            title = clean_text(item.get_text())
            if title and len(title) > 5:
                content_summary = deepseek_summarize(title)
                items.append({
                    "title": title,
                    "content": content_summary,
                    "timestamp": datetime.now().isoformat(),
                    "source": "cnBeta",
                    "url": item.get('href', '')
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
        self.sources = selected_sources or ["AKShare", "财联社", "华尔街见闻", "新浪科技", "36氪", "腾讯科技", "凤凰科技", "虎嗅网", "IT之家", "cnBeta", "Tushare", "东方财富", "新浪财经"]

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
            "Tushare": fetch_tushare,
            "东方财富": fetch_eastmoney,
            "新浪财经": fetch_sina_finance,
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

        # 2. 使用改进的DeepSeek提示词进行精确筛选
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
                    "content": news['content'],  # 使用已生成的概览
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
                print(f"  - 跳过非科技新闻: {news['title']}")

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