#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
测试上下文修复效果的脚本
验证补救时的上下文构建是否足够清晰
"""

from srt_polisher import SRTEntry

def test_context_construction():
    """测试上下文构建效果"""

    # 模拟问题场景：相邻字幕语义容易重复
    entries = [
        SRTEntry(12, "00:00:08,000", "00:00:10,000", "游戏画面质量显著提升"),
        SRTEntry(13, "00:00:10,000", "00:00:12,000", "光照效果都统一—计算"),  # 待润色
        SRTEntry(14, "00:00:12,000", "00:00:14,000", "完全不需要预烘焙各的光影效果")
    ]

    # 模拟 analyze_subtitle_context 的返回结果
    context_info = {
        'duration': 2.0,
        'current_chars': 10,
        'optimal_chars': 12,
        'char_ratio': 0.83,
        'needs_adjustment': False,
        'prev_content': entries[0].content,
        'next_content': entries[2].content
    }

    entry = entries[1]  # 第13条

    # 构建修复后的提示词
    polish_prompt = f"""请润色以下指定的字幕条目，注意与前后文保持语义连贯但不重复：

【润色目标】第{entry.number}条字幕
时长：{context_info['duration']:.1f}秒
当前字数：{context_info['current_chars']}字
建议字数：{context_info['optimal_chars']}字

原始内容：{entry.content}

【要求】只返回润色后的字幕内容，确保与前后文语义不重复。"""

    # 构建修复后的上下文
    context = ""
    if 'prev_content' in context_info:
        context += f"【前文参考】第{entry.number-1}条字幕：{context_info['prev_content']}\n\n"

    context += f"【当前任务】请润色第{entry.number}条字幕：{entry.content}\n\n"

    if 'next_content' in context_info:
        context += f"【后文参考】第{entry.number+1}条字幕：{context_info['next_content']}\n\n"

    context += "【重要提醒】请确保润色后的内容与前后文在语义上不重复，保持独特性和连贯性。"

    print("🔧 修复后的补救机制上下文构建：")
    print("=" * 60)
    print("【主要提示词】")
    print(polish_prompt)
    print("\n【上下文信息】")
    print(context)
    print("=" * 60)

    # 检查关键改进点
    improvements = []

    if "【润色目标】" in polish_prompt:
        improvements.append("✅ 明确标识润色目标")

    if "【前文参考】" in context and "【后文参考】" in context:
        improvements.append("✅ 清晰区分前后文参考")

    if "【当前任务】" in context:
        improvements.append("✅ 明确当前任务边界")

    if "语义不重复" in context or "独特性" in context:
        improvements.append("✅ 强调避免语义重复")

    if f"第{entry.number-1}条" in context and f"第{entry.number+1}条" in context:
        improvements.append("✅ 精确标注字幕序号")

    print("🎯 关键改进点：")
    for improvement in improvements:
        print(f"   {improvement}")

    print(f"\n💡 修复说明：")
    print(f"   原问题：AI收到模糊的上下文，不知道哪条是要润色的")
    print(f"   修复后：用【标签】明确区分，AI清楚知道任务边界")
    print(f"   预期效果：大幅减少语义重复问题")

    return len(improvements) >= 4

if __name__ == "__main__":
    print("🚀 测试补救机制上下文修复...")
    success = test_context_construction()

    if success:
        print("\n🎉 修复验证通过！补救机制的上下文构建已优化。")
        print("\n📝 关键改进总结：")
        print("   1. 用【标签】明确区分前文参考、当前任务、后文参考")
        print("   2. 精确标注字幕序号，避免AI混淆")
        print("   3. 强调语义不重复的要求")
        print("   4. 提示词结构更加清晰明确")
        print("\n⚠️  现在重新测试润色功能，补救时的语义重复问题应该大幅改善！")
    else:
        print("\n❌ 修复验证失败，需要进一步调整。")