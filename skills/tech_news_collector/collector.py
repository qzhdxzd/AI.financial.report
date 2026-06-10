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
def is_similar(t1, t2, thresh=0.6):  # 进一步降低相似度阈值
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
    prompt = f"""判断以下新闻是否与科技相关（AI、芯片、半导体、机器人、新能源、自动驾驶等）。
只输出JSON：{{"is_tech": true/false, "category": "领域名", "sentiment": "positive/negative/neutral"}}
标题：{title}
内容：{content[:300]}"""
    result = call_deepseek(prompt)
    if not result:
        return (True, "科技", "neutral")  # 如果API调用失败，默认认为是科技新闻
    try:
        data = json.loads(result)
        return (data.get("is_tech", True), data.get("category", "科技"), data.get("sentiment", "neutral"))
    except:
        return (True, "科技", "neutral")

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
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.telegraph-item .content')
        return [{
            "title": clean_text(item.select_one('a, div').get_text() if item.select_one('a, div') else ''),
            "content": clean_text(item.get_text()),
            "timestamp": datetime.now().isoformat(),
            "source": "财联社",
            "url": item.select_one('a')['href'] if item.select_one('a') and item.select_one('a').get('href') else ''
        } for item in items[:30] if item.get_text().strip()]
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
        response = requests.get(web_url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.live-list-item .title a')  # 调整选择器
        if not items:
            items = soup.select('.article-item .title a')  # 备用选择器
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
        "https://tech.sina.com.cn/roll/index.d.html?page=1",
        "https://roll.news.sina.com.cn/interface/rollnews_ch_out_interface.php?col=42",
    ]
    
    for url in urls:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = requests.get(url, timeout=10, headers=headers)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            news_items = []
            for item in soup.select('.list-blk li, .news-item'):  # 多种可能的选择器
                title_elem = item.select_one('a')
                if title_elem:
                    title = clean_text(title_elem.get_text())
                    link = title_elem.get('href', '')
                    if title:
                        news_items.append({
                            "title": title,
                            "content": "",
                            "timestamp": datetime.now().isoformat(),
                            "source": "新浪科技",
                            "url": link
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
            "Referer": "https://36kr.com/"
        }
        response = requests.get(url, timeout=10, headers=headers)
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
    """获取知乎日报科技类文章"""
    try:
        url = "https://news-at.zhihu.com/api/3/news/latest"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, timeout=10, headers=headers)
        data = response.json()
        return [{
            "title": clean_text(story.get('title', '')),
            "content": clean_text(story.get('title', '')),  # 使用标题作为内容
            "timestamp": datetime.now().isoformat(),
            "source": "知乎日报",
            "url": story.get('url', '')
        } for story in data.get('stories', [])[:15]]
    except Exception as e:
        print(f"知乎日报数据获取失败: {e}")
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
            link = item.get('href', '')
            if title and link:
                items.append({
                    "title": title,
                    "content": "",
                    "timestamp": datetime.now().isoformat(),
                    "source": "腾讯科技",
                    "url": link if link.startswith('http') else 'https://tech.qq.com' + link
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
            link = item.get('href', '')
            if title and link:
                items.append({
                    "title": title,
                    "content": "",
                    "timestamp": datetime.now().isoformat(),
                    "source": "凤凰科技",
                    "url": link
                })
        return items
    except Exception as e:
        print(f"凤凰科技数据获取失败: {e}")
        return []

def fetch_baidu_top():
    """获取百度搜索风云榜科技类"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get("http://top.baidu.com/buzz?b=11", timeout=10, headers=headers)
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

# ==================== 主采集器类 ====================
class TechNewsCollector:
    def __init__(self, use_mock=False, use_llm_filter=True, selected_sources=None):
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter
        self.sources = selected_sources or ["AKShare", "财联社", "华尔街见闻", "新浪科技", "36氪", "知乎日报", "腾讯科技", "凤凰科技", "百度热搜"]

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

        # 1. 多源采集
        all_news = []
        source_counts = {}
        
        source_functions = {
            "AKShare": fetch_akshare,
            "财联社": fetch_cls,
            "华尔街见闻": fetch_wallstreetcn,
            "新浪科技": fetch_sina_tech,
            "36氪": fetch_36kr,
            "知乎日报": fetch_zhihu_daily,
            "腾讯科技": fetch_tencent_tech,
            "凤凰科技": fetch_ifeng_tech,
            "百度热搜": fetch_baidu_top
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

        # 2. 使用DeepSeek进行精确筛选 - 这是唯一的筛选步骤
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

        # 3. 去重（进一步降低相似度阈值）
        unique = []
        for n in final_news:
            similar_found = False
            for u in unique:
                if is_similar(n['title'], u['title'], thresh=0.6):  # 进一步降低相似度阈值
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