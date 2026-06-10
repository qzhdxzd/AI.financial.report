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
def is_similar(t1, t2, thresh=0.85):
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
        return (False, "", "neutral")
    try:
        data = json.loads(result)
        return (data.get("is_tech", False), data.get("category", ""), data.get("sentiment", "neutral"))
    except:
        return (False, "", "neutral")

# ==================== 关键词保底库 ====================
KEYWORDS_FALLBACK = ["AI", "芯片", "半导体", "机器人", "英伟达", "中芯", "自动驾驶", "算力", "大模型", "GPU", "科技", "互联网", "软件", "硬件", "云计算", "大数据", "人工智能", "区块链", "物联网", "5G", "虚拟现实", "量子计算"]

def keyword_filter(news: Dict) -> bool:
    text = f"{news.get('title', '')} {news.get('content', '')}".lower()
    return any(kw.lower() in text for kw in KEYWORDS_FALLBACK)

# ==================== Hugging Face 零样本模型 ====================
_zero_shot = None

def get_zero_shot():
    global _zero_shot
    if _zero_shot is None:
        try:
            from transformers import pipeline
            print("正在加载零样本分类模型...")
            _zero_shot = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
                device=-1
            )
            print("HF模型加载成功")
        except Exception as e:
            print(f"HF模型加载失败（将使用关键词筛选）: {e}")
            _zero_shot = False
    return _zero_shot if _zero_shot is not False else None

def hf_is_tech(title: str, content: str, threshold: float = 0.4) -> bool:  # 降低阈值以获得更多信息
    classifier = get_zero_shot()
    if classifier is None:
        return False
    candidate_labels = ["科技", "财经", "娱乐", "体育", "政治"]
    text = f"{title}。{content}"[:500]
    result = classifier(text, candidate_labels)
    return result['labels'][0] == "科技" and result['scores'][0] > threshold

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
    # 首先尝试原API
    url = "https://api-web.itiger.com/v2/market/flash-list?page=1&column=global"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        data = requests.get(url, headers=headers, timeout=10).json()
        tiger_news = [{
            "title": clean_text(item.get('title', item.get('content', ''))[:100]),
            "content": clean_text(item.get('content', '')),
            "timestamp": item.get('publish_time', datetime.now().isoformat()) if item.get('publish_time') else datetime.now().isoformat(),
            "source": "老虎财经",
            "url": item.get('link_url', '')
        } for item in data.get('data', {}).get('list', []) if item.get('content')]
        
        if tiger_news:
            return tiger_news
    except Exception as e:
        print(f"老虎财经API获取失败: {e}")

    # 如果原API失败，尝试华尔街见闻
    try:
        alt_url = "https://api-prod.wallstreetcn.com/apiv1/content/lives?channel=global&limit=30"
        data = requests.get(alt_url, headers=headers).json()
        wallstreet_news = [{
            "title": clean_text(item.get('content_text', '')[:100]),
            "content": clean_text(item.get('content_text', '')),
            "timestamp": item.get('created_at', datetime.now().isoformat()),
            "source": "华尔街见闻",
            "url": f"https://wallstreetcn.com/live/{item.get('id','')}"
        } for item in data.get('data', {}).get('items', []) if item.get('content_text')]
        
        if wallstreet_news:
            return wallstreet_news
    except Exception as e:
        print(f"华尔街见闻API获取失败: {e}")

    # 如果API都失败，尝试网页爬取
    try:
        web_url = "https://www.wallstreetcn.com/live/global"
        response = requests.get(web_url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.live-item')
        web_news = [{
            "title": clean_text(item.get_text()[:100]),
            "content": clean_text(item.get_text()),
            "timestamp": datetime.now().isoformat(),
            "source": "华尔街见闻",
            "url": "https://www.wallstreetcn.com/live/global"
        } for item in items[:20] if item.get_text().strip()]
        return web_news
    except Exception as e:
        print(f"华尔街见闻网页爬取失败: {e}")
        return []

def fetch_sina_tech():
    """获取新浪科技新闻"""
    url = "https://tech.sina.com.cn/roll/index.d.html?page=1"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, timeout=10, headers=headers)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        news_items = []
        for item in soup.select('.list-blk li'):
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
        return news_items[:20]
    except Exception as e:
        print(f"新浪科技数据获取失败: {e}")
        return []

def fetch_36kr():
    """获取36氪科技新闻"""
    url = "https://36kr.com/api/information-flow/article/latest?per_page=20"
    try:
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
    url = "https://news-at.zhihu.com/api/3/news/latest"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, timeout=10, headers=headers)
        data = response.json()
        return [{
            "title": clean_text(story.get('title', '')),
            "content": "",
            "timestamp": datetime.now().isoformat(),
            "source": "知乎日报",
            "url": story.get('url', '')
        } for story in data.get('stories', [])[:15]]
    except Exception as e:
        print(f"知乎日报数据获取失败: {e}")
        return []

def fetch_tencent_news():
    """获取腾讯新闻科技频道"""
    try:
        url = "https://rabc2.50bang.org/api/getData.do?bizCode=yidian&siteId=33649&pageNum=1&pageSize=20&typeIds=13"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, timeout=10, headers=headers)
        data = response.json()
        return [{
            "title": clean_text(item.get('title', '')),
            "content": clean_text(item.get('content', '')),
            "timestamp": item.get('pubTime', datetime.now().isoformat()),
            "source": "腾讯新闻",
            "url": item.get('url', '')
        } for item in data.get('data', {}).get('list', []) if item.get('title')]
    except Exception as e:
        print(f"腾讯新闻数据获取失败: {e}")
        # 备用方法：直接爬取页面
        try:
            page_url = "https://new.qq.com/ch/tech"
            response = requests.get(page_url, timeout=10, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            items = soup.select('.Q-tpWrap h3 a')
            return [{
                "title": clean_text(item.get_text()),
                "content": "",
                "timestamp": datetime.now().isoformat(),
                "source": "腾讯新闻",
                "url": item.get('href', '')
            } for item in items[:15] if item.get_text().strip()]
        except Exception as e2:
            print(f"腾讯新闻备用方法也失败: {e2}")
            return []

def fetch_ifeng_news():
    """获取凤凰新闻科技频道"""
    try:
        url = "https://api.iclient.ifeng.com/ClientNews?id=SYLB10,SYDT10&pullNum=0&specialType="
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, timeout=10, headers=headers)
        data = response.json()
        tech_news = []
        for doc in data.get('SYDT10', []):
            if 'tech' in doc.get('newsType', '').lower() or '科技' in doc.get('title', ''):
                tech_news.append({
                    "title": clean_text(doc.get('title', '')),
                    "content": clean_text(doc.get('description', '')),
                    "timestamp": doc.get('updateTime', datetime.now().isoformat()),
                    "source": "凤凰新闻",
                    "url": doc.get('url', '')
                })
        return tech_news[:15]
    except Exception as e:
        print(f"凤凰新闻数据获取失败: {e}")
        return []

# ==================== 主采集器类 ====================
class TechNewsCollector:
    def __init__(self, use_mock=False, use_llm_filter=True, use_hf_filter=False, selected_sources=None):
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter
        self.use_hf_filter = use_hf_filter
        self.sources = selected_sources or ["AKShare", "财联社", "老虎财经", "新浪科技", "36氪", "知乎日报", "腾讯新闻"]

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
        
        if "AKShare" in self.sources:
            news = fetch_akshare(['000977','002230','300750','688981'])
            all_news.extend(news)
            source_counts["AKShare"] = len(news)
            
        if "财联社" in self.sources:
            news = fetch_cls()
            all_news.extend(news)
            source_counts["财联社"] = len(news)
            
        if "老虎财经" in self.sources or "华尔街见闻" in self.sources:
            news = fetch_wallstreetcn()
            all_news.extend(news)
            source_counts["老虎财经/华尔街见闻"] = len(news)
            
        if "新浪科技" in self.sources:
            news = fetch_sina_tech()
            all_news.extend(news)
            source_counts["新浪科技"] = len(news)
            
        if "36氪" in self.sources:
            news = fetch_36kr()
            all_news.extend(news)
            source_counts["36氪"] = len(news)
            
        if "知乎日报" in self.sources:
            news = fetch_zhihu_daily()
            all_news.extend(news)
            source_counts["知乎日报"] = len(news)
            
        if "腾讯新闻" in self.sources:
            news = fetch_tencent_news()
            all_news.extend(news)
            source_counts["腾讯新闻"] = len(news)
            
        if "凤凰新闻" in self.sources:
            news = fetch_ifeng_news()
            all_news.extend(news)
            source_counts["凤凰新闻"] = len(news)

        print(f"原始采集: {len(all_news)} 条来自 {len([k for k, v in source_counts.items() if v > 0])} 个不同来源")
        for source, count in source_counts.items():
            if count > 0:
                print(f"  - {source}: {count} 条")

        if not all_news:
            print("无采集数据，使用保底模拟数据")
            return self._get_fallback_news()

        # 2. 初筛：关键词筛选（更宽松的条件）
        candidates = []
        if self.use_hf_filter:
            hf = get_zero_shot()
            if hf is not None:
                print("使用 HF 模型进行初筛...")
                for news in all_news:
                    if hf_is_tech(news['title'], news.get('content', ''), threshold=0.4):  # 降低阈值
                        candidates.append(news)
                print(f"HF 初筛通过: {len(candidates)} 条")
            else:
                print("HF不可用，使用关键词筛选")
                candidates = [n for n in all_news if keyword_filter(n)]
                print(f"关键词筛选: {len(candidates)} 条")
        else:
            # 未启用 HF 筛选时，用关键词过滤，但放宽条件
            candidates = [n for n in all_news if keyword_filter(n) or len(n['title']) > 10]  # 即使不匹配关键词，标题较长的也保留
            print(f"关键词预筛: {len(candidates)} 条")

        if not candidates:
            print("初筛无结果，使用保底模拟数据")
            return self._get_fallback_news()

        # 3. DeepSeek 精筛（如果可用）
        final_news = []
        if self.use_llm_filter and DEEPSEEK_API_KEY:
            print("使用 DeepSeek 精筛...")
            for idx, news in enumerate(candidates):
                print(f"DeepSeek 进度: {idx+1}/{len(candidates)}")
                is_tech, cat, sent = deepseek_classify(news['title'], news.get('content', '')[:300])
                if is_tech:
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
            # 无 DeepSeek，直接使用初筛结果，但确保是科技相关内容
            for news in candidates:
                # 再次简单检查是否与科技相关，避免过多无关内容
                title_content = f"{news['title']} {news.get('content', '')}".lower()
                if any(keyword.lower() in title_content for keyword in ['科技', '技术', '互联网', 'AI', '智能', '芯片', '数据']):
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
                        "tech_category": "科技",
                        "tech_sentiment": "neutral",
                        "prediction_score": 0.0,
                        "impact_score": 0.0
                    })

        # 4. 去重（保持来源多样性）
        unique = []
        sources_used = {}  # 记录各来源已使用的数量
        
        for n in final_news:
            source = n['source']
            # 检查是否与已有的新闻相似
            is_duplicate = False
            for u in unique:
                if is_similar(n['title'], u['title']):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                # 确保每个来源都有一定比例的新闻
                if source not in sources_used:
                    sources_used[source] = 0
                # 限制单个来源的最大占比，避免某一来源占主导地位
                total_count = len(unique)
                source_count = sources_used[source]
                
                # 如果当前来源占比过高，则跳过
                if total_count > 5 and (source_count + 1) / (total_count + 1) > 0.4:
                    continue
                
                unique.append(n)
                sources_used[source] += 1

        print(f"最终科技新闻: {len(unique)} 条，来自 {len(set(n['source'] for n in unique))} 个不同来源")
        for source, count in sources_used.items():
            print(f"  - {source}: {count} 条")
        
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