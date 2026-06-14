"""
Claw3 专属：完整报告评分模块
满分100，四大维度各25分
"""
def score_finance_report(report_text: str) -> str:
    total_score = 0
    comment_list = []

    # 维度1：大盘、板块、个股数据完整性（25分）
    if "大盘" in report_text and "板块" in report_text and "个股" in report_text:
        total_score += 25
        comment_list.append("✅ 数据维度完整（25/25）")
    else:
        comment_list.append("❌ 缺少部分市场数据（0/25）")

    # 维度2：行情走势分析（25分）
    if "上涨" in report_text or "下跌" in report_text or "走势" in report_text:
        total_score += 25
        comment_list.append("✅ 行情逻辑分析到位（25/25）")
    else:
        comment_list.append("❌ 缺少行情解读（0/25）")

    # 维度3：风险提示（25分）
    if "风险" in report_text or "谨慎" in report_text or "波动" in report_text:
        total_score += 25
        comment_list.append("✅ 包含风险提示（25/25）")
    else:
        comment_list.append("❌ 未提示市场风险（0/25）")

    # 维度4：操作建议（25分）
    if "建议" in report_text or "观望" in report_text or "关注" in report_text:
        total_score += 25
        comment_list.append("✅ 操作建议完整（25/25）")
    else:
        comment_list.append("❌ 缺少操作建议（0/25）")

    final_text = f"""
# 报告评分结果
综合得分：{total_score} / 100
{chr(10).join(comment_list)}
"""
    return final_text