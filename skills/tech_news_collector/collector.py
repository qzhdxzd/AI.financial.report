#!/usr/bin/env python3
"""
科技财经新闻采集器 - Claw1 核心代码
支持关键词筛选 + 大模型智能筛选（DeepSeek）
"""

import json
import os
import hashlib
import argparse
import re
from datetime import datetime
from typing import List, Dict, Optional
import requests

# 尝试导入 akshare
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("Warning: akshare 未安装，将使用模拟数据模式")

# 从环境变量读取 DeepSeek API Key
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def call_deepseek(prompt: str, max_tokens=100) -> str:
    """调用 DeepSeek API"""
    if not DEEPSEEK_API_KEY:
        return ""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"LLM 调用失败: {e}")
    return ""

def is_tech_news_llm(title: str, content: str) -> tuple:
    """
    使用大模型判断新闻是否与科技股相关
    返回: (is_tech: bool, category: str, sentiment: str)
    """
    if not DEEPSEEK_API_KEY:
        # 如果没有 API Key，回退到关键词
        return False, "", "neutral"
    prompt = f"""判断以下新闻是否与科技股（如AI、芯片、半导体、机器人、算力、新能源车、自动驾驶等）相关。
如果相关，请输出 JSON 格式：{{"is_tech": true, "category": "具体板块", "sentiment": "positive/negative/neutral"}}
如果不相关，输出 {{"is_tech": false}}
新闻标题：{title}
新闻内容：{content[:200]}"""
    result = call_deepseek(prompt, max_tokens=100)
    try:
        import json
        data = json.loads(result)
        return data.get("is_tech", False), data.get("category", ""), data.get("sentiment", "neutral")
    except:
        # 如果解析失败，简单判断是否包含 "true"
        return "true" in result.lower(), "", "neutral"

class TechNewsCollector:
    def __init__(self, keywords: List[str] = None, use_mock: bool = False, use_llm_filter: bool = False):
        self.keywords = keywords or [
            "AI", "人工智能", "芯片", "半导体", "机器人", "算力", "数据中心",
            "云计算", "新能源车", "自动驾驶", "AI芯片", "GPU", "大模型"
        ]
        self.use_mock = use_mock or not AKSHARE_AVAILABLE
        self.use_llm_filter = use_llm_filter  # 是否使用大模型筛选
        self.tech_stocks = [
            '000977', '002230', '300750', '002475', '300308',
            '688981', '002415', '000063'
        ]

    def fetch_stock_news(self, symbol: str) -> List[Dict]:
        """获取单个股票的财经新闻"""
        if self.use_mock:
            return []
        try:
            news_df = ak.stock_news_em(symbol=symbol)
            if news_df is not None and not news_df.empty:
                return news_df.to_dict('records')
        except Exception as e:
            print(f"采集 {symbol} 新闻失败: {e}")
        return []

    def filter_tech_news_keyword(self, all_news: List[Dict]) -> List[Dict]:
        """关键词筛选（快速预筛）"""
        filtered = []
        for news in all_news:
            title = news.get('title', '')
            content = news.get('content', '')
            text = f"{title} {content}".lower()
            if any(kw.lower() in text for kw in self.keywords):
                filtered.append(news)
        return filtered

    def filter_tech_news_llm(self, news_list: List[Dict]) -> List[Dict]:
        """使用大模型逐条筛选科技新闻，并添加额外字段"""
        tech_news = []
        total = len(news_list)
        for idx, news in enumerate(news_list):
            title = news.get('title', '')
            content = news.get('content', '')
            print(f"LLM 筛选进度: {idx+1}/{total}")
            is_tech, category, sentiment = is_tech_news_llm(title, content)
            if is_tech:
                news['tech_category'] = category
                news['tech_sentiment'] = sentiment
                tech_news.append(news)
        print(f"LLM 筛选完成，科技新闻 {len(tech_news)} 条")
        return tech_news

    def extract_predictive_sentences(self, text: str) -> List[str]:
        prediction_keywords = ['预计', '有望', '可能', '将', '预期', '预测', '展望']
        sentences = re.split(r'[。；！]', text)
        result = []
        for sent in sentences:
            sent = sent.strip()
            if any(kw in sent for kw in prediction_keywords) and len(sent) > 5:
                result.append(sent)
        return result

    def _is_factual(self, text: str) -> bool:
        fact_patterns = [
            r'\d+%', r'\d+亿', r'\d+万元', r'同比增长', r'环比增长',
            r'公告', r'签署', r'合同', r'中标', r'预增', r'预亏'
        ]
        return any(re.search(p, text) for p in fact_patterns)

    def _extract_stocks(self, text: str) -> List[str]:
        codes = re.findall(r'\b[0-9]{6}\b', text)
        name_keywords = ['英伟达', 'AMD', '英特尔', '华为', '腾讯', '阿里', '字节']
        found_names = [name for name in name_keywords if name in text]
        return list(set(codes + found_names))

    def clean_news(self, news: Dict) -> Dict:
        title = news.get('title', '')
        content = news.get('content', '')
        full_text = f"{title} {content}"
        unique_str = f"{title}{news.get('publish_time', '')}{news.get('source', '')}"
        news_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]
        cleaned = {
            "id": news_id,
            "timestamp": news.get('publish_time', datetime.now().isoformat()),
            "source": news.get('source', 'akshare'),
            "title": title,
            "content": content[:500],
            "url": news.get('url', ''),
            "stock_mentioned": self._extract_stocks(full_text),
            "is_fact": self._is_factual(full_text),
            "predictive_sentences": self.extract_predictive_sentences(full_text)
        }
        # 如果大模型筛选时有额外字段，保留
        if 'tech_category' in news:
            cleaned['tech_category'] = news['tech_category']
            cleaned['tech_sentiment'] = news['tech_sentiment']
        return cleaned

    def get_mock_news(self) -> List[Dict]:
        """模拟新闻数据（包含科技相关）"""
        return [
            {
                "id": "mock1",
                "timestamp": datetime.now().isoformat(),
                "source": "模拟财经",
                "title": "英伟达发布新一代AI芯片，算力提升3倍",
                "content": "英伟达今日宣布推出新一代AI加速卡，预计将带动全球AI算力需求大幅增长。",
                "url": "",
                "stock_mentioned": ["英伟达", "AI"],
                "is_fact": True,
                "predictive_sentences": ["预计将带动全球AI算力需求大幅增长"],
                "tech_category": "AI芯片",
                "tech_sentiment": "positive"
            },
            {
                "id": "mock2",
                "timestamp": datetime.now().isoformat(),
                "source": "模拟财经",
                "title": "半导体行业传出利好，多家公司财报超预期",
                "content": "台积电、中芯国际等芯片代工厂季度营收同比增长超过20%，行业景气度回升。",
                "url": "",
                "stock_mentioned": ["中芯国际", "半导体"],
                "is_fact": True,
                "predictive_sentences": [],
                "tech_category": "半导体",
                "tech_sentiment": "positive"
            },
            {
                "id": "mock3",
                "timestamp": datetime.now().isoformat(),
                "source": "模拟财经",
                "title": "工信部：加快推进人工智能与实体经济深度融合",
                "content": "工信部相关负责人表示，下一步将出台更多政策支持AI产业发展。",
                "url": "",
                "stock_mentioned": ["AI", "人工智能"],
                "is_fact": True,
                "predictive_sentences": ["将出台更多政策支持AI产业发展"],
                "tech_category": "AI",
                "tech_sentiment": "positive"
            }
        ]

    def collect(self) -> List[Dict]:
        if self.use_mock:
            print(f"[{datetime.now()}] 使用模拟数据模式")
            return self.get_mock_news()

        print(f"[{datetime.now()}] 开始采集科技新闻...")
        all_news = []
        for code in self.tech_stocks:
            news = self.fetch_stock_news(code)
            print(f"采集 {code}: {len(news)} 条")
            all_news.extend(news)

        print(f"总新闻数: {len(all_news)}")

        if self.use_llm_filter and DEEPSEEK_API_KEY:
            # 大模型筛选（更准确）
            tech_news = self.filter_tech_news_llm(all_news)
        else:
            # 关键词筛选（快速）
            tech_news = self.filter_tech_news_keyword(all_news)

        print(f"筛选后科技新闻: {len(tech_news)} 条")
        cleaned = [self.clean_news(n) for n in tech_news]
        
        # 去重
        seen = set()
        unique = []
        for n in cleaned:
            if n['id'] not in seen:
                seen.add(n['id'])
                unique.append(n)
        print(f"去重后: {len(unique)} 条")
        return unique

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--mock', action='store_true', help='使用模拟数据')
    parser.add_argument('--use-llm', action='store_true', help='使用大模型筛选（需要 DeepSeek API Key）')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    collector = TechNewsCollector(use_mock=args.mock, use_llm_filter=args.use_llm)
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