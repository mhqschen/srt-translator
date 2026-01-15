#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import sys
import argparse
import random
from typing import List, Dict, Tuple, Optional
import logging
import colorama
from colorama import Fore, Style

# 初始化colorama以支持彩色输出
colorama.init()

# 设置Windows编码
if sys.platform == 'win32':
    import codecs
    try:
        if (
            sys.stdout is not None
            and not getattr(sys.stdout, "closed", False)
            and hasattr(sys.stdout, "buffer")
            and sys.stdout.buffer is not None
            and not getattr(sys.stdout.buffer, "closed", False)
        ):
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        if (
            sys.stderr is not None
            and not getattr(sys.stderr, "closed", False)
            and hasattr(sys.stderr, "buffer")
            and sys.stderr.buffer is not None
            and not getattr(sys.stderr.buffer, "closed", False)
        ):
            sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")
    except Exception:
        pass

# 设置日志
_handlers = [logging.FileHandler("srt_checker.log", encoding="utf-8")]
_suppress_console = os.environ.get("SRT_SUPPRESS_CONSOLE_LOG", "0") == "1"
if not _suppress_console and sys.stderr is not None:
    _handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger("SRT-Checker")

# 定义SRT条目的正则表达式
SRT_PATTERN = re.compile(
    r'(\d+)\s*\n'               # 字幕序号
    r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n'  # 时间码
    r'((?:.+(?:\n|$))+?)'       # 字幕内容（可能多行，最后一行可能没有换行符）
    r'(?:\n|$)',                # 空行或文件结尾
    re.MULTILINE
)

class SRTEntry:
    """表示SRT文件中的一个字幕条目"""
    def __init__(self, number: int, start_time: str, end_time: str, content: str):
        self.number = number
        self.start_time = start_time
        self.end_time = end_time
        self.content = content.strip()
    
    def to_string(self) -> str:
        """将字幕条目转换为SRT格式字符串"""
        return f"{self.number}\n{self.start_time} --> {self.end_time}\n{self.content}\n"
    
    def __str__(self) -> str:
        return self.to_string()
    
    def is_bilingual(self) -> bool:
        """检测是否为双语字幕（包含原文和译文的多行格式）"""
        lines = self.content.split('\n')
        return len(lines) >= 2 and len(lines[0].strip()) > 0 and len(lines[1].strip()) > 0
    
    def __repr__(self) -> str:
        return f"SRTEntry({self.number}, {self.start_time}, {self.end_time}, {self.content})"

def parse_srt_file(srt_file_path: str) -> List[SRTEntry]:
    """解析SRT文件，返回字幕条目列表"""
    try:
        with open(srt_file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # 确保文件末尾有换行符，这样正则表达式更容易匹配最后一个条目
        if not content.endswith('\n'):
            content += '\n'
        
        entries = []
        for match in SRT_PATTERN.finditer(content):
            number = int(match.group(1))
            start_time = match.group(2)
            end_time = match.group(3)
            subtitle_content = match.group(4)
            
            entries.append(SRTEntry(number, start_time, end_time, subtitle_content))
        
        logger.info(f"已从 {srt_file_path} 解析 {len(entries)} 个字幕条目")
        return entries
    
    except Exception as e:
        logger.error(f"解析SRT文件 {srt_file_path} 出错: {e}")
        raise

def check_srt_files(source_file: str, translated_file: str, output_file: Optional[str] = None, use_colors: bool = True) -> bool:
    """检查源SRT文件和翻译后的SRT文件是否匹配"""
    try:
        # 解析源文件和翻译文件
        source_entries = parse_srt_file(source_file)
        translated_entries = parse_srt_file(translated_file)
        
        # 检查条目数量是否相同
        if len(source_entries) != len(translated_entries):
            logger.error(f"条目数量不匹配: 源文件 {len(source_entries)} 个, 翻译文件 {len(translated_entries)} 个")
            perfect_match = False
        else:
            logger.info(f"条目数量匹配: 源文件和翻译文件均有 {len(source_entries)} 个条目")
            perfect_match = True
        
        # 创建源文件条目字典，方便快速查找
        source_dict = {entry.number: entry for entry in source_entries}
        
        # 检查每个条目
        mismatches = []
        missing_numbers = []
        
        for trans_entry in translated_entries:
            if trans_entry.number not in source_dict:
                missing_numbers.append(trans_entry.number)
                perfect_match = False
                continue
            
            source_entry = source_dict[trans_entry.number]
            issues = []
            
            # 检查时间码
            if source_entry.start_time != trans_entry.start_time:
                issues.append(f"起始时间码不匹配: 源={source_entry.start_time}, 译={trans_entry.start_time}")
                perfect_match = False
            
            if source_entry.end_time != trans_entry.end_time:
                issues.append(f"结束时间码不匹配: 源={source_entry.end_time}, 译={trans_entry.end_time}")
                perfect_match = False
            
            if issues:
                mismatches.append((trans_entry.number, issues))
        
        # 检查翻译文件是否缺失源文件中的条目
        translated_numbers = {entry.number for entry in translated_entries}
        source_numbers = {entry.number for entry in source_entries}
        missing_from_translated = source_numbers - translated_numbers
        
        if missing_from_translated:
            logger.error(f"翻译文件缺少的条目编号: {', '.join(map(str, sorted(missing_from_translated)))}")
            perfect_match = False
        
        # 输出检查结果
        if perfect_match:
            if use_colors:
                print(f"{Fore.GREEN}✓ 完美匹配！源文件和翻译文件的时间码和字幕编号完全一致。{Style.RESET_ALL}")
            else:
                print("✓ 完美匹配！源文件和翻译文件的时间码和字幕编号完全一致。")
            
            # 添加更多详细信息（即使完美匹配）
            total_entries = len(source_entries)
            if use_colors:
                print(f"\n{Fore.CYAN}【字幕文件详细信息】{Style.RESET_ALL}")
            else:
                print("\n【字幕文件详细信息】")
            print(f"总条目数: {total_entries}")
            
            # 检测双语格式
            bilingual_count = sum(1 for entry in translated_entries if entry.is_bilingual())
            if bilingual_count > 0:
                percentage = (bilingual_count / total_entries) * 100
                print(f"双语条目: {bilingual_count}/{total_entries} ({percentage:.1f}%)")
                if percentage > 90:
                    if use_colors:
                        print(f"{Fore.GREEN}✓ 这是双语字幕文件{Style.RESET_ALL}")
                    else:
                        print("✓ 这是双语字幕文件")
                elif percentage > 50:
                    if use_colors:
                        print(f"{Fore.YELLOW}⚠ 部分双语字幕格式{Style.RESET_ALL}")
                    else:
                        print("⚠ 部分双语字幕格式")
                else:
                    if use_colors:
                        print(f"{Fore.YELLOW}⚠ 少量双语条目{Style.RESET_ALL}")
                    else:
                        print("⚠ 少量双语条目")
            else:
                if use_colors:
                    print(f"{Fore.BLUE}ℹ 这是单语字幕文件{Style.RESET_ALL}")
                else:
                    print("ℹ 这是单语字幕文件")
            
            if total_entries > 0:
                # 显示第一条字幕
                first_entry = source_entries[0]
                if use_colors:
                    print(f"\n{Fore.CYAN}第一条字幕 (#{first_entry.number}):{Style.RESET_ALL}")
                else:
                    print(f"\n第一条字幕 (#{first_entry.number}):")
                print(f"  时间码: {first_entry.start_time} --> {first_entry.end_time}")
                print(f"  📄 原文: {first_entry.content}")
                trans_first = next((e for e in translated_entries if e.number == first_entry.number), None)
                if trans_first:
                    print(f"  🌐 译文: {trans_first.content}")
                    print("  " + "─" * 50)
                
                # 显示最后一条字幕
                last_entry = source_entries[-1]
                if use_colors:
                    print(f"\n{Fore.CYAN}最后一条字幕 (#{last_entry.number}):{Style.RESET_ALL}")
                else:
                    print(f"\n最后一条字幕 (#{last_entry.number}):")
                print(f"  时间码: {last_entry.start_time} --> {last_entry.end_time}")
                print(f"  📄 原文: {last_entry.content}")
                trans_last = next((e for e in translated_entries if e.number == last_entry.number), None)
                if trans_last:
                    print(f"  🌐 译文: {trans_last.content}")
                    print("  " + "─" * 50)
                
                # 显示更多随机抽样的字幕条目
                sample_size = min(8, total_entries - 2)  # 增加到8个样本
                if sample_size > 0:
                    # 确保有足够的条目可供抽样
                    try:
                        sample_indices = random.sample(range(1, total_entries-1), sample_size)
                        if use_colors:
                            print(f"\n{Fore.CYAN}随机抽样的字幕条目 (共{sample_size}个):{Style.RESET_ALL}")
                        else:
                            print(f"\n随机抽样的字幕条目 (共{sample_size}个):")
                        
                        for idx in sample_indices:
                            sample_entry = source_entries[idx]
                            if use_colors:
                                print(f"\n{Fore.CYAN}样本字幕 (#{sample_entry.number}):{Style.RESET_ALL}")
                            else:
                                print(f"\n样本字幕 (#{sample_entry.number}):")
                            print(f"  时间码: {sample_entry.start_time} --> {sample_entry.end_time}")
                            print(f"  📄 原文: {sample_entry.content}")
                            trans_sample = next((e for e in translated_entries if e.number == sample_entry.number), None)
                            if trans_sample:
                                print(f"  🌐 译文: {trans_sample.content}")
                                print("  " + "─" * 50)
                    except ValueError:
                        # 如果条目太少无法抽样，则提示用户
                        if use_colors:
                            print(f"\n{Fore.YELLOW}字幕条目数量较少，无法提供更多随机样本。{Style.RESET_ALL}")
                        else:
                            print("\n字幕条目数量较少，无法提供更多随机样本。")
        else:
            if use_colors:
                print(f"{Fore.RED}✗ 检测到不匹配！{Style.RESET_ALL}")
            else:
                print("✗ 检测到不匹配！")
            
            if missing_numbers:
                if use_colors:
                    print(f"{Fore.YELLOW}翻译文件中存在源文件没有的条目编号: {', '.join(map(str, sorted(missing_numbers)))}{Style.RESET_ALL}")
                else:
                    print(f"翻译文件中存在源文件没有的条目编号: {', '.join(map(str, sorted(missing_numbers)))}")
            
            if missing_from_translated:
                if use_colors:
                    print(f"{Fore.YELLOW}翻译文件缺少的条目编号: {', '.join(map(str, sorted(missing_from_translated)))}{Style.RESET_ALL}")
                else:
                    print(f"翻译文件缺少的条目编号: {', '.join(map(str, sorted(missing_from_translated)))}")
            
            if mismatches:
                if use_colors:
                    print(f"\n{Fore.CYAN}时间码不匹配的条目:{Style.RESET_ALL}")
                else:
                    print("\n时间码不匹配的条目:")
                for number, issues in mismatches:
                    if use_colors:
                        print(f"{Fore.CYAN}条目 #{number}:{Style.RESET_ALL}")
                    else:
                        print(f"条目 #{number}:")
                    for issue in issues:
                        if use_colors:
                            print(f"  {Fore.RED}- {issue}{Style.RESET_ALL}")
                        else:
                            print(f"  - {issue}")
        
        # 同时将结果写入日志（不带颜色代码）
        if perfect_match:
            logger.info("✓ 完美匹配！源文件和翻译文件的时间码和字幕编号完全一致。")
            logger.info("【字幕文件详细信息】")
            logger.info(f"总条目数: {len(source_entries)}")
            
            # 检测双语格式
            bilingual_count = sum(1 for entry in translated_entries if entry.is_bilingual())
            if bilingual_count > 0:
                percentage = (bilingual_count / len(source_entries)) * 100
                logger.info(f"双语条目: {bilingual_count}/{len(source_entries)} ({percentage:.1f}%)")
                if percentage > 90:
                    logger.info("✓ 这是双语字幕文件")
                elif percentage > 50:
                    logger.info("⚠ 部分双语字幕格式")
                else:
                    logger.info("⚠ 少量双语条目")
            else:
                logger.info("ℹ 这是单语字幕文件")
            
            if len(source_entries) > 0:
                # 记录第一条字幕
                first_entry = source_entries[0]
                logger.info(f"第一条字幕 (#{first_entry.number}):")
                logger.info(f"时间码: {first_entry.start_time} --> {first_entry.end_time}")
                logger.info(f"原文: {first_entry.content}")
                trans_first = next((e for e in translated_entries if e.number == first_entry.number), None)
                if trans_first:
                    logger.info(f"译文: {trans_first.content}")
                
                # 记录最后一条字幕
                last_entry = source_entries[-1]
                logger.info(f"最后一条字幕 (#{last_entry.number}):")
                logger.info(f"时间码: {last_entry.start_time} --> {last_entry.end_time}")
                logger.info(f"原文: {last_entry.content}")
                trans_last = next((e for e in translated_entries if e.number == last_entry.number), None)
                if trans_last:
                    logger.info(f"译文: {trans_last.content}")
        else:
            logger.info("✗ 检测到不匹配！")
            
            if missing_numbers:
                logger.info(f"翻译文件中存在源文件没有的条目编号: {', '.join(map(str, sorted(missing_numbers)))}")
            
            if missing_from_translated:
                logger.info(f"翻译文件缺少的条目编号: {', '.join(map(str, sorted(missing_from_translated)))}")
            
            if mismatches:
                logger.info("时间码不匹配的条目:")
                for number, issues in mismatches:
                    logger.info(f"条目 #{number}:")
                    for issue in issues:
                        logger.info(f"  - {issue}")
        
        # 如果指定了输出文件，将详细报告写入文件
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# SRT文件检查报告\n\n")
                f.write(f"源文件: {source_file}\n")
                f.write(f"翻译文件: {translated_file}\n\n")
                
                f.write(f"## 总体结果\n\n")
                if perfect_match:
                    f.write("✓ 完美匹配！源文件和翻译文件的时间码和字幕编号完全一致。\n\n")
                else:
                    f.write("✗ 检测到不匹配！\n\n")
                
                f.write(f"源文件条目数: {len(source_entries)}\n")
                f.write(f"翻译文件条目数: {len(translated_entries)}\n\n")
                
                if missing_numbers:
                    f.write(f"## 翻译文件中存在源文件没有的条目编号\n\n")
                    for number in sorted(missing_numbers):
                        entry = next((e for e in translated_entries if e.number == number), None)
                        if entry:
                            f.write(f"#{number}: {entry.start_time} --> {entry.end_time}\n")
                            f.write(f"{entry.content}\n\n")
                
                if missing_from_translated:
                    f.write(f"## 翻译文件缺少的条目编号\n\n")
                    for number in sorted(missing_from_translated):
                        entry = source_dict[number]
                        f.write(f"#{number}: {entry.start_time} --> {entry.end_time}\n")
                        f.write(f"{entry.content}\n\n")
                
                if mismatches:
                    f.write(f"## 时间码不匹配的条目\n\n")
                    for number, issues in mismatches:
                        source_entry = source_dict[number]
                        trans_entry = next((e for e in translated_entries if e.number == number), None)
                        
                        f.write(f"### 条目 #{number}\n\n")
                        f.write(f"**源文件**:\n")
                        f.write(f"{source_entry.start_time} --> {source_entry.end_time}\n")
                        f.write(f"{source_entry.content}\n\n")
                        
                        f.write(f"**翻译文件**:\n")
                        if trans_entry:
                            f.write(f"{trans_entry.start_time} --> {trans_entry.end_time}\n")
                            f.write(f"{trans_entry.content}\n\n")
                        
                        f.write(f"**问题**:\n")
                        for issue in issues:
                            f.write(f"- {issue}\n")
                        f.write("\n")
                
                logger.info(f"详细报告已写入: {output_file}")
        
        return perfect_match
    
    except Exception as e:
        logger.error(f"检查SRT文件时出错: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def main():
    parser = argparse.ArgumentParser(description="SRT字幕文件校验工具 - 检查时间码和字幕编号是否匹配")
    parser.add_argument("source_file", help="源SRT文件路径")
    parser.add_argument("translated_file", help="翻译后的SRT文件路径")
    parser.add_argument("--output", "-o", help="输出详细报告的文件路径")
    parser.add_argument("--no-colors", action="store_true", help="不使用颜色输出（适用于日志文件）")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.source_file):
        logger.error(f"源文件不存在: {args.source_file}")
        return 1
    
    if not os.path.exists(args.translated_file):
        logger.error(f"翻译文件不存在: {args.translated_file}")
        return 1
    
    logger.info(f"开始检查源文件 {args.source_file} 和翻译文件 {args.translated_file}")
    perfect_match = check_srt_files(args.source_file, args.translated_file, args.output, not args.no_colors)
    
    # 返回代码: 0表示完全匹配，1表示存在不匹配
    return 0 if perfect_match else 1

if __name__ == "__main__":
    exit(main()) 
