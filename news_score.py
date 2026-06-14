import json
import re
import os
import sys
from typing import Dict, List, Any

# ==================== 配置参数 ====================
SOURCE_ACCURACY: Dict[str, float] = {
    "财联社": 0.65,
    "华尔街见闻": 0.60,
    "36氪": 0.55,
    "新浪财经": 0.50,
    "东方财富": 0.48,
    "同花顺": 0.52,
    "第一财经": 0.58,
    "证券时报": 0.56,
    "default": 0.50
}

# 确定性系数映射 —— 与 EXTRACT_KEYWORDS 保持同步
# 财经/科技新闻语境下，已发生的事实动作应有高确定性
CERTAINTY_MAP: Dict[str, float] = {
    # ═══ 高确定性 0.90-1.0：已完成的官方动作 ═══
    "毫无疑问": 1.0, "必然": 1.0, "确定": 0.95, "正式发布": 0.95, "正式": 0.95,
    "大幅": 1.0, "明显": 0.95, "强势": 0.95,
    "达成": 0.92, "推出": 0.90, "申报": 0.90,
    "上市": 0.90, "获批": 0.95, "发布": 0.90,
    # ═══ 中高确定性 0.80-0.89：强趋势/明确计划 ═══
    "大概率": 0.85, "上涨": 0.85, "下跌": 0.85,
    "增长": 0.85, "下降": 0.85, "突破": 0.85, "跌破": 0.85,
    "上调": 0.85, "下调": 0.85,
    "有望": 0.82, "计划": 0.82, "拟": 0.80,
    "合作": 0.80, "开发": 0.78,
    # ═══ 中等确定性 0.70-0.79：合理预期 ═══
    "预计": 0.75, "预期": 0.75, "或将": 0.72,
    "即将": 0.72, "准备": 0.70, "选择": 0.70,
    "调整": 0.70, "推进": 0.72,
    # ═══ 中低确定性 0.55-0.69：推测性表述 ═══
    "可能": 0.65, "接近": 0.62,
    "将": 0.60, "会": 0.58, "考虑": 0.55,
    # ═══ 低确定性 0.30-0.54：不确定/传闻 ═══
    "或": 0.50, "或许": 0.45, "不排除": 0.40,
    # ═══ 极低确定性 0.10-0.29：明确传闻 ═══
    "传闻": 0.20, "据传": 0.18, "疑似": 0.22,
    "default": 0.75  # 提高默认值：能被提取关键词匹配到的句子，默认就有中等偏上的确定性
}

# 用于提取句子的关键词（只使用多字关键词，避免单字误匹配）
EXTRACT_KEYWORDS = [
    "即将", "可能", "有望", "预计", "预期", "大概率",
    "不排除", "传闻", "据传", "大幅", "明显", "确定",
    "正式发布", "推出", "上调", "下跌", "上涨", "增长", "下降", "突破",
    "跌破", "选择", "达成", "合作", "开发", "申报", "调整",
    "或将", "计划", "准备", "考虑", "疑似"
]

def load_source_accuracy(filepath: str = "source_accuracy.json") -> Dict[str, float]:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return SOURCE_ACCURACY

def save_source_accuracy(acc: Dict[str, float], filepath: str = "source_accuracy.json"):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(acc, f, ensure_ascii=False, indent=2)

def get_certainty_coefficient(text: str) -> float:
    """根据文本内容返回确定性系数（取匹配到的最高系数，单字词只在不构成更长词时生效）"""
    # 按关键词长度降序排列，长词优先匹配
    sorted_kw = sorted(
        [(k, v) for k, v in CERTAINTY_MAP.items() if k != "default"],
        key=lambda x: len(x[0]), reverse=True
    )
    matched_coeffs = []
    matched_longest_len = 0

    for keyword, coeff in sorted_kw:
        if keyword in text:
            kw_len = len(keyword)
            # 单字关键词（长度=1）只在没有更长匹配时才加入
            if kw_len == 1 and matched_longest_len > 1:
                continue
            matched_coeffs.append(coeff)
            if kw_len > matched_longest_len:
                matched_longest_len = kw_len

    if matched_coeffs:
        return max(matched_coeffs)
    return CERTAINTY_MAP["default"]

# DeepSeek筛选后的信源可信度加成系数
FILTERED_SOURCE_BOOST = 1.35  # 筛选后的新闻，信源可信度提升35%


def score_prediction(pred_text: str, source_accuracy: float, filtered: bool = False) -> float:
    """对单条预测语句打分 = 信源准确率 × 确定性系数（可选筛选加成）"""
    coeff = get_certainty_coefficient(pred_text)
    if filtered:
        # 已筛选新闻：提升信源权重，但不超过1.0
        source_accuracy = min(source_accuracy * FILTERED_SOURCE_BOOST, 1.0)
    return round(source_accuracy * coeff, 4)

def extract_predictions_from_text(text: str) -> List[str]:
    """
    从文本中提取包含 EXTRACT_KEYWORDS 中任意关键词的句子。
    按句号、感叹号、问号、分号分隔。
    返回去重后的句子列表（保持顺序）。
    """
    if not text:
        return []
    # 分割句子（中文标点）
    sentences = re.split(r'[。！？；]', text)
    predictions = []
    seen = set()
    for sent in sentences:
        sent = sent.strip()
        if not sent or sent in seen:
            continue
        # 检查是否包含任意关键词
        if any(kw in sent for kw in EXTRACT_KEYWORDS):
            predictions.append(sent)
            seen.add(sent)
    return predictions

def process_news(news: Dict[str, Any], source_acc: Dict[str, float],
                 filtered: bool = False) -> Dict[str, Any]:
    """对单条新闻打分：提取预测句 → 逐句评分 → 计算综合分
    Args:
        news: 新闻字典，需含 source/title/content
        source_acc: 信源准确率表
        filtered: 是否已经过DeepSeek等LLM筛选（筛选过的新闻可信度更高）
    """
    source = news.get("source", "default")
    if source not in source_acc:
        source = "default"
    src_acc = source_acc[source]

    # 优先使用已有的 predictions，若为空则自动提取
    existing_preds = news.get("predictions", [])
    if existing_preds:
        predictions = existing_preds
    else:
        title = news.get("title", "")
        content = news.get("content", "")
        combined_text = title + "。" + content
        auto_preds = extract_predictions_from_text(combined_text)
        news["predictions"] = auto_preds
        predictions = auto_preds

    if not predictions:
        news["predictions_score"] = 0.0
        news["scored_predictions"] = []
        return news

    scored = []
    total = 0.0
    for pred in predictions:
        score = score_prediction(pred, src_acc, filtered=filtered)
        scored.append({"text": pred, "score": score})
        total += score

    avg_score = total / len(predictions)
    news["predictions_score"] = round(avg_score, 4)
    news["scored_predictions"] = scored
    return news

def main(input_file: str, output_file: str, source_acc_file: str = None):
    if source_acc_file and os.path.exists(source_acc_file):
        source_accuracy = load_source_accuracy(source_acc_file)
    else:
        source_accuracy = SOURCE_ACCURACY.copy()
    
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if isinstance(data, dict) and 'news' in data:
        news_list = data['news']
    elif isinstance(data, list):
        news_list = data
    else:
        raise ValueError("输入的JSON结构不正确，应为列表或包含'news'键的对象")
    
    processed_news = [process_news(news, source_accuracy) for news in news_list]
    
    if isinstance(data, dict) and 'news' in data:
        data['news'] = processed_news
        output_data = data
    else:
        output_data = processed_news
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 处理完成！共处理 {len(processed_news)} 条新闻，结果保存至 {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python news_score.py <输入JSON文件> <输出JSON文件> [信源准确率文件]")
        sys.exit(1)
    input_json = sys.argv[1]
    output_json = sys.argv[2]
    acc_file = sys.argv[3] if len(sys.argv) > 3 else None
    main(input_json, output_json, acc_file)