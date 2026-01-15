#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import re
import os
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

def _setup_windows_stdout_for_cli() -> None:
    if sys.platform != "win32":
        return
    try:
        import codecs

        out = getattr(sys, "stdout", None)
        if out is None or getattr(out, "closed", False):
            return
        buf = getattr(out, "buffer", None)
        if buf is None or getattr(buf, "closed", False):
            return
        sys.stdout = codecs.getwriter("utf-8")(buf, "strict")
    except Exception:
        return

def parse_srt_file(file_path):
    """解析SRT文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    pattern = re.compile(
        r'(\d+)\s*\n'
        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n'
        r'((?:.+(?:\n|$))+?)'
        r'(?:\n|$)',
        re.MULTILINE
    )
    
    entries = []
    for match in pattern.finditer(content):
        number = int(match.group(1))
        start_time = match.group(2)
        end_time = match.group(3)
        subtitle_content = match.group(4).strip()
        entries.append({
            'number': number,
            'start_time': start_time,
            'end_time': end_time,
            'content': subtitle_content
        })
    
    return entries

def normalize_subtitle_text(text: str) -> str:
    """规范化字幕文本，将多行合并为尽可能少的行"""
    # 移除多余的空白字符
    text = text.strip()
    
    # 将换行符替换为空格，然后清理多余空格
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    
    return text

def clean_translation_result(translation: str, original: str) -> str:
    """智能清理翻译结果，保留译文中的英文内容"""
    translation = translation.strip()
    original = original.strip()
    
    if translation == original:
        return ""
    
    # 方法1: 如果原文完全包含在翻译中，直接替换
    if original in translation:
        result = translation.replace(original, '', 1).strip()
        # 清理开头可能的标点和空格
        result = result.lstrip(' \t.,!?;:"""\'\'')
        if result:
            return result
    
    # 方法2: 按单词智能分割（保留译文中的英文）
    # 检查是否是"原文 译文"的简单格式
    if translation.startswith(original):
        # 如果翻译以原文开头，取原文后面的部分
        result = translation[len(original):].strip()
        # 清理开头的标点符号
        result = result.lstrip(' \t.,!?;:"""\'\'')
        if result:
            return result
    
    # 方法3: 智能识别混合内容
    # 尝试找到原文结束的位置
    original_words = original.lower().split()
    translation_words = translation.split()
    
    # 查找原文在翻译中的位置
    for i in range(len(translation_words) - len(original_words) + 1):
        # 检查从位置i开始是否匹配原文
        match = True
        for j, orig_word in enumerate(original_words):
            if i + j >= len(translation_words):
                match = False
                break
            trans_word = translation_words[i + j].lower().strip('.,!?;:"""\'\'')
            if trans_word != orig_word.lower().strip('.,!?;:"""\'\''):
                match = False
                break
        
        if match:
            # 找到匹配，取原文后面的所有内容作为译文
            remaining_words = translation_words[i + len(original_words):]
            if remaining_words:
                return ' '.join(remaining_words).strip()
    
    # 方法4: 如果都没找到明确的分割点，检查是否包含中文
    # 如果包含中文，说明是译文，直接返回
    if re.search(r'[\u4e00-\u9fff]', translation):
        return translation
    
    # 方法5: 最后的保护措施 - 如果译文明显比原文长，可能是正确的
    if len(translation) > len(original) * 1.2:  # 译文比原文长20%以上
        return translation
    
    # 如果所有方法都失败，返回原始翻译（保守处理）
    return translation

def process_single_entry(args):
    """处理单个字幕条目的函数，用于多线程"""
    orig, trans, verbose = args
    
    if orig['number'] != trans['number']:
        if verbose:
            print(f"⚠️ 条目编号不匹配：{orig['number']} vs {trans['number']}")
        return None
    
    # 规范化英文内容（移除不必要的换行）
    normalized_original = normalize_subtitle_text(orig['content'])
    
    # 清理译文，移除可能包含的原文
    clean_translation = clean_translation_result(trans['content'], orig['content'])
    
    # 生成双语内容
    bilingual_content = f"{normalized_original}\n{clean_translation}"
    
    if verbose:
        print(f"处理条目 {trans['number']}:")
        print(f"  时间轴: {trans['start_time']} --> {trans['end_time']}")
        print(f"  原文: {orig['content']}")
        print(f"  规范化原文: {normalized_original}")
        print(f"  译文: {trans['content']}")
        print(f"  清理后: {clean_translation}")
        print(f"  双语格式:\n{bilingual_content}")
        print("-" * 40)
    
    return {
        'number': trans['number'],
        'start_time': trans['start_time'],
        'end_time': trans['end_time'],
        'content': bilingual_content
    }

def convert_to_bilingual(original_file, translated_file, output_file, max_workers=None, progress_callback=None, stop_event=None):
    """将单语翻译转换为双语格式，支持多线程和进度回调"""
    
    # 初始化进度报告
    if progress_callback:
        progress_callback(0.0, "开始读取文件...")
    
    print(f"读取原文件: {original_file}")
    original_entries = parse_srt_file(original_file)
    print(f"解析到 {len(original_entries)} 个原文条目")
    
    if progress_callback:
        progress_callback(0.1, "原文件解析完成")
    
    print(f"读取译文件: {translated_file}")
    translated_entries = parse_srt_file(translated_file)
    print(f"解析到 {len(translated_entries)} 个译文条目")
    
    if progress_callback:
        progress_callback(0.2, "译文件解析完成")
    
    if len(original_entries) != len(translated_entries):
        print(f"⚠️ 条目数量不匹配：原文{len(original_entries)}个，译文{len(translated_entries)}个")
        return False
    
    total_entries = len(original_entries)
    bilingual_entries = [None] * total_entries  # 预分配列表保持顺序
    
    if progress_callback:
        progress_callback(0.25, f"准备处理 {total_entries} 个字幕条目")
    
    # 准备参数列表
    args_list = [(original_entries[i], translated_entries[i], False) for i in range(total_entries)]
    
    # 使用多线程处理
    if max_workers is None:
        max_workers = min(8, os.cpu_count() or 1)  # 默认最多8个线程
    
    print(f"使用 {max_workers} 个线程并行处理...")
    
    if progress_callback:
        progress_callback(0.3, f"启动 {max_workers} 个并行处理线程")
    
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_index = {executor.submit(process_single_entry, args_list[i]): i 
                          for i in range(total_entries)}
        
        for future in concurrent.futures.as_completed(future_to_index):
            # 检查停止信号
            if stop_event and stop_event.is_set():
                print("收到停止信号，正在终止处理...")
                # 取消未完成的任务
                for f in future_to_index:
                    f.cancel()
                return False
            
            index = future_to_index[future]
            try:
                result = future.result()
                if result:
                    bilingual_entries[index] = result
                completed += 1
                
                # 更新进度 - 从30%开始到90%结束，留10%给写文件
                progress = 0.3 + (completed / total_entries) * 0.6  # 30%-90%
                if progress_callback:
                    progress_callback(progress, f"已处理 {completed}/{total_entries} 个条目")
                else:
                    print(f"进度: {progress:.1%} ({completed}/{total_entries})")
                    
            except Exception as e:
                print(f"处理条目 {index} 时出错: {e}")
                completed += 1
    
    # 过滤掉None值
    valid_entries = [entry for entry in bilingual_entries if entry is not None]
    
    if not valid_entries:
        print("❌ 没有有效的条目可以写入")
        return False
    
    if progress_callback:
        progress_callback(0.9, f"开始写入 {len(valid_entries)} 个条目到文件")
    
    # 写入双语文件
    print(f"写入双语文件: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        for i, entry in enumerate(valid_entries):
            f.write(f"{entry['number']}\n")
            f.write(f"{entry['start_time']} --> {entry['end_time']}\n")
            f.write(f"{entry['content']}\n")
            if i < len(valid_entries) - 1:
                f.write("\n")
            
            # 写入进度报告
            if progress_callback and i % 100 == 0:  # 每100条报告一次
                write_progress = 0.9 + (i / len(valid_entries)) * 0.1  # 90%-100%
                progress_callback(write_progress, f"写入进度 {i+1}/{len(valid_entries)}")
    
    if progress_callback:
        progress_callback(1.0, "文件写入完成")
    
    print(f"✓ 双语文件已生成: {output_file}")
    print(f"✓ 成功处理 {len(valid_entries)} 个条目")
    return True

if __name__ == "__main__":
    _setup_windows_stdout_for_cli()
    print("使用方法:")
    print("python independent_bilingual_translator.py 原文.srt 译文.srt 双语输出.srt")
    print()
    
    if len(sys.argv) != 4:
        print("请提供正确的参数")
        sys.exit(1)
    
    original_file = sys.argv[1]
    translated_file = sys.argv[2]
    output_file = sys.argv[3]
    
    if not os.path.exists(original_file):
        print(f"原文文件不存在: {original_file}")
        sys.exit(1)
    
    if not os.path.exists(translated_file):
        print(f"译文文件不存在: {translated_file}")
        sys.exit(1)
    
    success = convert_to_bilingual(original_file, translated_file, output_file)
    if success:
        print("\n🎉 转换完成！")
        print(f"请检查生成的双语文件: {output_file}")
    else:
        print("\n❌ 转换失败！")
        sys.exit(1)
