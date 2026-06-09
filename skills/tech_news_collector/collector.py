#!/usr/bin/env python3
"""科技财经新闻采集器 - Claw1 - 纯大模型智能筛选"""

import json
import os
import hashlib
import re
from datetime import datetime
from typing import List, Dict, Optional
import requests

# 从环境变量读取 DeepSeek API Key
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def call_deepseek(prompt: str, max_tokens: int = 50) -> str:
    """调用 DeepSeek API，返回文本"""
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
        else:
            error = resp.json().get("error", {}).get("message", "未知错误")
            print(f"API 调用失败: {error}")
            return ""
    except Exception as e:
        print(f"API 请求异常: {e}")
        return ""

def llm_classify_news(title: str, content: str) -> tuple:
    """使用大模型判断新闻是否科技相关，并返回类别和情感"""
    if not DEEPSEEK_API_KEY:
        return False, "", "neutral"
    prompt = f"""判断以下新闻是否与科技股（AI、芯片、半导体、机器人、新能源、自动驾驶等）相关。
如果相关，输出 JSON：{{"is_tech": true, "category": "具体板块", "sentiment": "positive/negative/neutral"}}
如果不相关，输出 {{"is_tech": false}}
新闻标题：{title}
新闻内容：{content[:300]}"""
    result = call_deepseek(prompt, max_tokens=80)
    try:
        import json
        data = json.loads(result)
        return data.get("is_tech", False), data.get("category", ""), data.get("sentiment", "neutral")
    except:
        # 如果解析失败，简单判断是否包含 true
        return "true" in result.lower(), "", "neutral"

class TechNewsCollector:
    def __init__(self, use_mock: bool = False):
        """
        :param use_mock: 是否使用模拟数据（用于演示或API不可用时）
        """
        self.use_mock = use_mock
        self.tech_stocks = [
            '000977', '002230', '300750', '002475', '300308',
            '688981', '002415', '000063'
        ]

    def fetch_stock_news(self, symbol: str) -> List[Dict]:
        """获取单只股票的新闻"""
        if self.use_mock:
            return []
        try:
            import akshare as ak
            news_df = ak.stock_news_em(symbol=symbol)
            if news_df is not None and not news_df.empty:
                return news_df.to_dict('records')
        except Exception as e:
            print(f"采集 {symbol} 新闻失败: {e}")
        return []

    def clean_news(self, news: Dict, category: str = "", sentiment: str = "neutral") -> Dict:
        """清洗新闻，添加元数据"""
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
            "predictive_sentences": self._extract_predictive(full_text),
            "tech_category": category,
            "tech_sentiment": sentiment
        }
        return cleaned

    def _extract_stocks(self, text: str) -> List[str]:
        codes = re.findall(r'\b[0-9]{6}\b', text)
        names = ['英伟达', 'AMD', '英特尔', '华为', '腾讯', '阿里', '字节', '中芯国际']
        found = [name for name in names if name in text]
        return list(set(codes + found))

    def _is_factual(self, text: str) -> bool:
        patterns = [r'\d+%', r'\d+亿', r'同比增长', r'公告', r'合同', r'中标', r'预增']
        return any(re.search(p, text) for p in patterns)

    def _extract_predictive(self, text: str) -> List[str]:
        keywords = ['预计', '有望', '可能', '将', '预期']
        sentences = re.split(r'[。；！]', text)
        return [s.strip() for s in sentences if any(k in s for k in keywords) and len(s) > 5]

    def get_mock_news(self) -> List[Dict]:
        """模拟科技新闻（用于演示或API不可用）"""
        now = datetime.now().isoformat()
        return [
            {
                "id": "mock1",
                "timestamp": now,
                "source": "模拟财经",
                "title": "英伟达发布新一代AI芯片，算力提升3倍",
                "content": "英伟达今日宣布推出新一代AI加速卡，预计将带动全球AI算力需求大幅增长。",
                "url": "",
                "stock_mentioned": ["英伟达", "AI芯片"],
                "is_fact": True,
                "predictive_sentences": ["预计将带动全球AI算力需求大幅增长"],
                "tech_category": "AI芯片",
                "tech_sentiment": "positive"
            },
            {
                "id": "mock2",
                "timestamp": now,
                "source": "模拟财经",
                "title": "中芯国际季度营收超预期，半导体行业回暖",
                "content": "中芯国际公告显示，三季度营收同比增长34%，超出市场预期。",
                "url": "",
                "stock_mentioned": ["中芯国际", "半导体"],
                "is_fact": True,
                "predictive_sentences": [],
                "tech_category": "半导体",
                "tech_sentiment": "positive"
            },
            {
                "id": "mock3",
                "timestamp": now,
                "source": "模拟财经",
                "title": "工信部：加快推动人工智能与实体经济深度融合",
                "content": "工信部表示，将出台更多政策支持AI产业发展。",
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

        tech_news = []
        total = len(all_news)
        for idx, news in enumerate(all_news):
            print(f"LLM 筛选进度: {idx+1}/{total}")
            title = news.get('title', '')
            content = news.get('content', '')[:300]
            is_tech, category, sentiment = llm_classify_news(title, content)
            if is_tech:
                cleaned = self.clean_news(news, category, sentiment)
                tech_news.append(cleaned)

        print(f"大模型筛选完成，科技新闻 {len(tech_news)} 条")
        # 去重（基于 id）
        seen = set()
        unique = []
        for n in tech_news:
            if n['id'] not in seen:
                seen.add(n['id'])
                unique.append(n)
        print(f"去重后: {len(unique)} 条")
        return unique

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