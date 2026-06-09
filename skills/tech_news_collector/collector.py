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

# Hugging Face 零样本分类器（全局懒加载）
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
            print(f"HF模型加载失败: {e}")
            _zero_shot = False
    return _zero_shot if _zero_shot is not False else None

def hf_is_tech(title: str, content: str, threshold: float = 0.6) -> bool:
    classifier = get_zero_shot()
    if classifier is None:
        return False
    candidate_labels = ["科技", "财经", "娱乐", "体育", "政治"]
    text = f"{title}。{content}"[:500]
    result = classifier(text, candidate_labels)
    return result['labels'][0] == "科技" and result['scores'][0] > threshold

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

# ---------------------------- 数据源采集 ----------------------------
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
        soup = BeautifulSoup(requests.get(url, timeout=10).text, 'html.parser')
        items = soup.select('.telegraph-item')
        return [{
            "title": clean_text(t.select_one('.title').get_text()),
            "content": "",
            "timestamp": datetime.now().isoformat(),
            "source": "财联社",
            "url": ""
        } for t in items[:30] if t.select_one('.title')]
    except:
        return []

def fetch_wallstreetcn():
    url = "https://api-prod.wallstreetcn.com/apiv1/content/lives?channel=global&limit=30"
    try:
        data = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}).json()
        return [{
            "title": clean_text(item.get('content_text', '')[:100]),
            "content": clean_text(item.get('content_text', '')),
            "timestamp": item.get('created_at', datetime.now().isoformat()),
            "source": "华尔街见闻",
            "url": f"https://wallstreetcn.com/live/{item.get('id','')}"
        } for item in data.get('data', {}).get('items', []) if item.get('content_text')]
    except:
        return []

def fetch_sina():
    url = "https://finance.sina.com.cn/tech/"
    try:
        soup = BeautifulSoup(requests.get(url, timeout=10).text, 'html.parser')
        return [{
            "title": clean_text(a.get_text()),
            "content": "",
            "timestamp": datetime.now().isoformat(),
            "source": "新浪科技",
            "url": a.get('href', '')
        } for a in soup.select('a[href*="/tech/"]')[:20] if len(clean_text(a.get_text())) > 5]
    except:
        return []

# ---------------------------- 主采集器 ----------------------------
class TechNewsCollector:
    def __init__(self, use_mock=False, use_llm_filter=True, use_hf_filter=False, selected_sources=None):
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter
        self.use_hf_filter = use_hf_filter
        self.sources = selected_sources or ["AKShare", "财联社", "华尔街见闻", "新浪科技"]

    def get_mock_news(self):
        now = datetime.now().isoformat()
        return [{
            "id": f"mock{i}", "timestamp": now, "source": "模拟数据",
            "title": t, "content": c, "url": "", "stock_mentioned": s,
            "is_fact": True, "predictive_sentences": [], "tech_category": cat,
            "tech_sentiment": "positive", "prediction_score": 0.0, "impact_score": 0.0
        } for i, (t, c, s, cat) in enumerate([
            ("英伟达发布新一代AI芯片H200，算力提升3倍", "英伟达今日宣布推出新一代AI加速卡H200...", ["英伟达"], "AI芯片"),
            ("中芯国际季度营收超预期，半导体行业回暖", "中芯国际公告显示，三季度营收同比增长34%...", ["中芯国际"], "半导体"),
            ("工信部：加快推动人工智能与实体经济深度融合", "工信部相关负责人表示，将出台更多政策支持AI产业发展...", ["AI"], "AI")
        ], 1)]

    def collect(self):
        if self.use_mock:
            print("使用模拟数据")
            return self.get_mock_news()

        # 1. 多源采集
        all_news = []
        if "AKShare" in self.sources: all_news.extend(fetch_akshare(['000977','002230','300750']))
        if "财联社" in self.sources: all_news.extend(fetch_cls())
        if "华尔街见闻" in self.sources: all_news.extend(fetch_wallstreetcn())
        if "新浪科技" in self.sources: all_news.extend(fetch_sina())
        print(f"原始采集: {len(all_news)} 条")

        if not all_news:
            return self.get_mock_news()

        # 2. 初筛：优先使用HF零样本，否则用关键词保底
        candidates = []
        if self.use_hf_filter:
            hf_model = get_zero_shot()
            if hf_model is not None:
                print("使用 HF 模型进行初筛...")
                for idx, news in enumerate(all_news):
                    title = news['title']
                    content = news.get('content', '')
                    if hf_is_tech(title, content, threshold=0.6):
                        candidates.append(news)
                print(f"HF 初筛通过: {len(candidates)} 条")
            else:
                print("HF不可用，使用关键词保底")
                keywords = ["AI", "芯片", "半导体", "机器人", "英伟达", "中芯", "自动驾驶", "算力"]
                candidates = [n for n in all_news if any(k in n['title'] for k in keywords)]
                print(f"关键词保底筛选: {len(candidates)} 条")
        else:
            # 如果未启用 HF 筛选，可以不做初筛，直接进入下一步，但为了效率，仍用简单关键词过滤
            keywords = ["AI", "芯片", "半导体", "机器人", "英伟达", "中芯", "自动驾驶", "算力"]
            candidates = [n for n in all_news if any(k in n['title'] for k in keywords)]
            print(f"关键词预筛: {len(candidates)} 条")

        if not candidates:
            print("初筛无结果，返回模拟数据")
            return self.get_mock_news()

        # 3. DeepSeek 精筛（可选）
        final_news = []
        if self.use_llm_filter and DEEPSEEK_API_KEY:
            print("使用 DeepSeek 精筛...")
            for idx, news in enumerate(candidates):
                print(f"DeepSeek 进度: {idx+1}/{len(candidates)}")
                is_tech, cat, sent = deepseek_classify(news['title'], news.get('content','')[:300])
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
            # 无 DeepSeek，直接使用初筛结果
            for news in candidates:
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

        # 4. 去重
        unique = []
        for n in final_news:
            if not any(is_similar(n['title'], u['title']) for u in unique):
                unique.append(n)
        print(f"最终科技新闻: {len(unique)} 条")
        return unique if unique else self.get_mock_news()