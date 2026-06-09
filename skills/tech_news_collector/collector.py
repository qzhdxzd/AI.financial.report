#!/usr/bin/env python3
"""
科技财经新闻采集器 - Claw1
支持多数据源 + 关键词初筛 + HF零样本模型 + 大模型精筛 + 相似度去重
预留 prediction_score / impact_score 接口
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

# 尝试导入 akshare
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("Warning: akshare 未安装")

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Hugging Face 零样本分类器（全局懒加载）
_zero_shot_classifier = None

def get_zero_shot_classifier():
    """懒加载零样本分类模型"""
    global _zero_shot_classifier
    if _zero_shot_classifier is None:
        try:
            from transformers import pipeline
            print("正在加载零样本分类模型（首次加载需下载，约1.6GB）...")
            _zero_shot_classifier = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
                device=-1  # 使用CPU，可改为0使用GPU（如果有）
            )
            print("模型加载完成。")
        except Exception as e:
            print(f"加载HF模型失败: {e}")
            _zero_shot_classifier = False
    return _zero_shot_classifier if _zero_shot_classifier is not False else None

def hf_tech_filter(title: str, content: str, threshold: float = 0.7) -> bool:
    """使用零样本分类判断是否为科技新闻"""
    classifier = get_zero_shot_classifier()
    if classifier is None:
        return False
    candidate_labels = ["科技", "财经", "娱乐", "体育", "政治"]
    text = f"{title}。{content}"[:500]
    result = classifier(text, candidate_labels)
    return result['labels'][0] == "科技" and result['scores'][0] > threshold

# ==================== 科技关键词库（用于初筛） ====================
TECH_KEYWORDS = [
    "AI", "人工智能", "大模型", "深度学习", "机器学习", "神经网络", "自然语言",
    "芯片", "半导体", "集成电路", "CPU", "GPU", "NPU", "FPGA", "ASIC",
    "算力", "云计算", "边缘计算", "数据中心", "服务器", "光模块",
    "自动驾驶", "无人驾驶", "智能驾驶", "机器人", "具身智能", "工业机器人",
    "新能源车", "电动车", "动力电池", "固态电池", "燃料电池", "储能",
    "5G", "6G", "通信", "物联网", "车联网",
    "英伟达", "NVIDIA", "AMD", "Intel", "英特尔", "华为", "中芯国际",
    "台积电", "腾讯", "阿里", "百度", "字节跳动", "OpenAI", "ChatGPT",
    "Copilot", "Gemini", "Claude", "DeepSeek"
]

# ==================== 辅助函数 ====================
def is_similar(title1: str, title2: str, threshold: float = 0.85) -> bool:
    return SequenceMatcher(None, title1, title2).ratio() > threshold

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
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        else:
            print(f"API 错误 {resp.status_code}")
            return None
    except Exception as e:
        print(f"API 异常: {e}")
        return None

def llm_classify_news(title: str, content: str) -> tuple:
    if not DEEPSEEK_API_KEY:
        return (False, "", "neutral")
    prompt = f"""判断以下新闻是否与科技相关（包括AI、芯片、半导体、机器人、新能源、自动驾驶、科技公司财报、技术突破、行业政策）。
只输出JSON：{{"is_tech": true/false, "category": "领域名", "sentiment": "positive/negative/neutral"}}
新闻标题：{title}
新闻内容：{content[:300]}"""
    result = call_deepseek(prompt, max_tokens=80)
    if not result:
        return (False, "", "neutral")
    try:
        data = json.loads(result)
        return (data.get("is_tech", False), data.get("category", ""), data.get("sentiment", "neutral"))
    except:
        return (False, "", "neutral")

def keyword_filter(news: Dict) -> bool:
    title = news.get('title', '')
    content = news.get('content', '')
    full_text = f"{title} {content}".lower()
    return any(kw.lower() in full_text for kw in TECH_KEYWORDS)

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# ==================== 数据源采集函数 ====================
def fetch_akshare_news(stock_codes: List[str]) -> List[Dict]:
    if not AKSHARE_AVAILABLE:
        return []
    all_news = []
    for code in stock_codes:
        try:
            df = ak.stock_news_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    news = {
                        "title": clean_text(row.get('title', '')),
                        "content": clean_text(row.get('content', ''))[:500],
                        "timestamp": row.get('publish_time', datetime.now().isoformat()),
                        "source": "AKShare",
                        "url": row.get('url', ''),
                    }
                    all_news.append(news)
            time.sleep(0.5)
        except Exception as e:
            print(f"AKShare 采集 {code} 失败: {e}")
    return all_news

def fetch_cls_telegraph() -> List[Dict]:
    url = "https://www.cls.cn/telegraph"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.telegraph-item')
        news_list = []
        for item in items[:30]:
            title_elem = item.select_one('.title')
            if title_elem:
                title = clean_text(title_elem.get_text())
                news_list.append({
                    "title": title,
                    "content": title,
                    "timestamp": datetime.now().isoformat(),
                    "source": "财联社",
                    "url": ""
                })
        return news_list
    except Exception as e:
        print(f"财联社采集失败: {e}")
        return []

def fetch_wallstreetcn_live() -> List[Dict]:
    url = "https://api-prod.wallstreetcn.com/apiv1/content/lives?channel=global&limit=30"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://wallstreetcn.com/"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        items = data.get('data', {}).get('items', [])
        news_list = []
        for item in items:
            content = item.get('content_text', '')
            if content:
                news_list.append({
                    "title": clean_text(content[:100]),
                    "content": clean_text(content),
                    "timestamp": item.get('created_at', datetime.now().isoformat()),
                    "source": "华尔街见闻",
                    "url": f"https://wallstreetcn.com/live/{item.get('id', '')}"
                })
        return news_list
    except Exception as e:
        print(f"华尔街见闻采集失败: {e}")
        return []

def fetch_sina_news() -> List[Dict]:
    url = "https://finance.sina.com.cn/tech/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        news_list = []
        for link in soup.select('a[href*="/tech/"]')[:20]:
            title = clean_text(link.get_text())
            if title and len(title) > 5:
                news_list.append({
                    "title": title,
                    "content": title,
                    "timestamp": datetime.now().isoformat(),
                    "source": "新浪科技",
                    "url": link.get('href', '')
                })
        return news_list
    except Exception as e:
        print(f"新浪科技采集失败: {e}")
        return []

# 可扩展的数据源（预留，UI中可选）
def fetch_36kr_news():
    # 示例：可加入36氪RSS解析
    return []

def fetch_tmtpost_news():
    return []

# ==================== 主采集器类 ====================
class TechNewsCollector:
    def __init__(self, use_mock: bool = False, use_llm_filter: bool = True,
                 use_hf_filter: bool = False, selected_sources: List[str] = None,
                 **kwargs):
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter
        self.use_hf_filter = use_hf_filter
        self.selected_sources = selected_sources or ["AKShare", "财联社", "华尔街见闻", "新浪科技"]
        self.tech_stocks = ['000977', '002230', '300750', '002475', '300308', '688981', '002415', '000063']

    def collect_from_all_sources(self) -> List[Dict]:
        all_news = []
        if "AKShare" in self.selected_sources:
            print("采集 AKShare...")
            all_news.extend(fetch_akshare_news(self.tech_stocks))
        if "财联社" in self.selected_sources:
            print("采集财联社...")
            all_news.extend(fetch_cls_telegraph())
        if "华尔街见闻" in self.selected_sources:
            print("采集华尔街见闻...")
            all_news.extend(fetch_wallstreetcn_live())
        if "新浪科技" in self.selected_sources:
            print("采集新浪科技...")
            all_news.extend(fetch_sina_news())
        # 扩展数据源
        if "36氪" in self.selected_sources:
            all_news.extend(fetch_36kr_news())
        if "钛媒体" in self.selected_sources:
            all_news.extend(fetch_tmtpost_news())
        return all_news

    def clean_news(self, news: Dict, category: str = "", sentiment: str = "neutral") -> Dict:
        title = news.get('title', '')
        content = news.get('content', '')
        full_text = f"{title} {content}"
        unique_str = f"{title}{news.get('timestamp', '')}{news.get('source', '')}"
        news_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]
        return {
            "id": news_id,
            "timestamp": news.get('timestamp', datetime.now().isoformat()),
            "source": news.get('source', '未知'),
            "title": title,
            "content": content[:500],
            "url": news.get('url', ''),
            "stock_mentioned": self._extract_stocks(full_text),
            "is_fact": self._is_factual(full_text),
            "predictive_sentences": self._extract_predictive(full_text),
            "tech_category": category,
            "tech_sentiment": sentiment,
            "prediction_score": 0.0,   # 预留给Claw2的打分接口
            "impact_score": 0.0
        }

    def _extract_stocks(self, text: str) -> List[str]:
        codes = re.findall(r'\b[0-9]{6}\b', text)
        names = ['英伟达', 'AMD', '英特尔', '华为', '腾讯', '阿里', '中芯国际']
        found = [n for n in names if n in text]
        return list(set(codes + found))

    def _is_factual(self, text: str) -> bool:
        return bool(re.search(r'\d+%|\d+亿|同比增长|公告|合同|中标', text))

    def _extract_predictive(self, text: str) -> List[str]:
        keywords = ['预计', '有望', '可能', '将', '预期']
        sents = re.split(r'[。；！]', text)
        return [s.strip() for s in sents if any(k in s for k in keywords) and len(s) > 5]

    def get_mock_news(self) -> List[Dict]:
        now = datetime.now().isoformat()
        return [
            {"id": "mock1", "timestamp": now, "source": "模拟数据", "title": "英伟达发布新一代AI芯片H200，算力提升3倍", "content": "英伟达今日宣布推出新一代AI加速卡H200...", "url": "", "stock_mentioned": ["英伟达"], "is_fact": True, "predictive_sentences": [], "tech_category": "AI芯片", "tech_sentiment": "positive", "prediction_score": 0.0, "impact_score": 0.0},
            {"id": "mock2", "timestamp": now, "source": "模拟数据", "title": "中芯国际季度营收超预期，半导体行业回暖", "content": "中芯国际公告显示，三季度营收同比增长34%...", "url": "", "stock_mentioned": ["中芯国际"], "is_fact": True, "predictive_sentences": [], "tech_category": "半导体", "tech_sentiment": "positive", "prediction_score": 0.0, "impact_score": 0.0},
            {"id": "mock3", "timestamp": now, "source": "模拟数据", "title": "工信部：加快推动人工智能与实体经济深度融合", "content": "工信部相关负责人表示，将出台更多政策支持AI产业发展...", "url": "", "stock_mentioned": ["AI"], "is_fact": True, "predictive_sentences": [], "tech_category": "AI", "tech_sentiment": "positive", "prediction_score": 0.0, "impact_score": 0.0}
        ]

    def collect(self) -> List[Dict]:
        if self.use_mock:
            print("使用模拟数据模式")
            return self.get_mock_news()

        print("开始采集真实新闻...")
        raw_news = self.collect_from_all_sources()
        print(f"原始采集总数: {len(raw_news)}")

        # 1. 关键词预筛选
        tech_candidates = [n for n in raw_news if keyword_filter(n)]
        print(f"关键词预筛选后: {len(tech_candidates)} 条")

        # 2. HF 零样本模型筛选（可选）
        if self.use_hf_filter:
            print("使用HF零样本模型进行精筛...")
            hf_filtered = []
            for n in tech_candidates:
                if hf_tech_filter(n.get('title',''), n.get('content','')):
                    hf_filtered.append(n)
            tech_candidates = hf_filtered
            print(f"HF模型筛选后: {len(tech_candidates)} 条")

        if not tech_candidates:
            print("预筛结果为空")
            return []

        # 3. 大模型精筛（可选）
        if self.use_llm_filter and DEEPSEEK_API_KEY:
            print("使用大模型精筛...")
            llm_tech = []
            total = len(tech_candidates)
            for idx, n in enumerate(tech_candidates):
                print(f"LLM进度: {idx+1}/{total}")
                is_tech, cat, sent = llm_classify_news(n.get('title',''), n.get('content','')[:300])
                if is_tech:
                    llm_tech.append(self.clean_news(n, cat, sent))
            if llm_tech:
                final_news = llm_tech
                print(f"大模型筛选得到 {len(final_news)} 条")
            else:
                print("大模型未识别到科技新闻，使用关键词结果")
                final_news = [self.clean_news(n, "科技", "neutral") for n in tech_candidates]
        else:
            final_news = [self.clean_news(n, "科技", "neutral") for n in tech_candidates]

        # 4. 相似度去重
        unique = []
        for n in final_news:
            if not any(is_similar(n['title'], u['title']) for u in unique):
                unique.append(n)
        print(f"最终科技新闻: {len(unique)} 条")
        return unique

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--no-llm', action='store_true')
    parser.add_argument('--hf', action='store_true', help='启用HF零样本筛选')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    collector = TechNewsCollector(use_mock=args.mock, use_llm_filter=not args.no_llm, use_hf_filter=args.hf)
    news_list = collector.collect()
    output = {"date": datetime.now().strftime("%Y-%m-%d"), "timestamp": datetime.now().isoformat(), "total": len(news_list), "news": news_list}
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ 保存至 {args.output}")

if __name__ == "__main__":
    main()