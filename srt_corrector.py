#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import argparse
import requests
import sys
import logging
from typing import List, Dict, Tuple, Optional, Union, Callable
import concurrent.futures
import threading

# 设置日志 - 修复Unicode编码问题
if sys.platform == 'win32':
    # 在Windows上使用UTF-8编码
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

_handlers = [logging.FileHandler("srt_corrector.log", encoding="utf-8")]
_suppress_console = os.environ.get("SRT_SUPPRESS_CONSOLE_LOG", "0") == "1"
if not _suppress_console and sys.stderr is not None:
    _handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger("SRT-Corrector")

# 重试与退避相关常量
MAX_API_RETRIES = 5  # API调用最大重试次数
MAX_ENTRY_RETRIES = 5  # 单条纠错最大重试次数
MAX_BATCH_RETRIES = 5  # 真批量模式最大重试次数
MAX_BACKOFF_SECONDS = 10  # 退避等待时间上限（秒）
BATCH_TIMEOUT_SECONDS = 180  # 批量请求固定超时时间（可被实例覆盖）

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

class CorrectionAPI:
    """统一的API接口封装，用于字幕纠错"""
    def __init__(self, api_type: str = "custom", api_key: str = "", 
                 api_endpoint: str = "", model: str = "", temperature: float = 0.3,
                 timeout_seconds: int = BATCH_TIMEOUT_SECONDS, log_callback=None):
        self.api_type = api_type
        self.api_key = api_key
        self.api_endpoint = api_endpoint
        self.model = model
        self.temperature = temperature
        self.log_callback = log_callback
        self.timeout_seconds = timeout_seconds
        
        # ASR来源与"不要改语法"的系统提示词
        self.system_prompt = """你是字幕听写纠错助手。这些字幕来自语音识别软件（如 Whisper）自动识别的结果。

## 核心原则
只有当原词与正确词**发音相近**时才进行修正。如果发音不相似，请保留原文。

## 请在不改变原意的前提下：
1. 修正因发音相近导致的听写/拼写错误
2. 仅移除标点前多余空格或修正明显的标点误用（不要主动添加标点）

## 绝对不要：
1. 更改语法或调整语序
2. 做措辞重写、同义替换或风格统一
3. 新增、删除或重排词语
4. 翻译文本
5. 根据你的知识"修正"你不认识的新产品名、新活动名等时效性内容

## 重要说明
- 你只负责修正"听错"，不负责修正"说错"——即使说话人可能用错了词，也要忠实还原
- 务必保持原有的换行与分隔符结构（例如"===SUBTITLE_SEPARATOR_X==="必须原样保留）
- 直接返回修正后的文本，不要解释说明"""

    def _log(self, message: str, level: str = "info"):
        """同时输出到日志和可选的GUI回调"""
        if level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        else:
            logger.info(message)

        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                # GUI 回调异常不影响主流程
                pass

    def correct_text(self, text: str, retry_count: int = MAX_API_RETRIES) -> Optional[str]:
        """使用API纠错文本（无上下文版本）"""
        return self.correct_text_with_context(text, None, retry_count)
    
    def correct_batch_texts(self, entries_batch: List[SRTEntry], all_entries: List[SRTEntry] = None, 
                           batch_start_idx: int = 0, context_window: int = 0, retry_count: int = MAX_API_RETRIES) -> List[Optional[str]]:
        """批量纠错多条字幕（支持上下文感知）"""
        if not entries_batch:
            return []
        
        # 准备上下文信息（如果提供了全部条目）
        context = ""
        if all_entries and context_window > 0:
            batch_end_idx = batch_start_idx + len(entries_batch)
            
            # 获取批次前的上下文
            context_before = []
            for i in range(max(0, batch_start_idx - context_window), batch_start_idx):
                context_before.append(f"第{all_entries[i].number}条: {all_entries[i].content}")
            
            # 获取批次后的上下文
            context_after = []
            for i in range(batch_end_idx, min(len(all_entries), batch_end_idx + context_window)):
                context_after.append(f"第{all_entries[i].number}条: {all_entries[i].content}")
            
            # 组合上下文信息
            if context_before:
                context += "前文参考：\n" + "\n".join(context_before) + "\n\n"
            if context_after:
                context += "后文参考：\n" + "\n".join(context_after) + "\n\n"
        
        # 构建批量纠错消息（使用分隔符）
        separator = "\n===SUBTITLE_SEPARATOR_{index}===\n"
        combined_content = ""
        
        for i, entry in enumerate(entries_batch):
            if i > 0:
                combined_content += separator.format(index=i)
            combined_content += entry.content
        
        # 构建完整的用户消息（强调不要更改语法）
        user_message = f"""请修正以下字幕中的听写/拼写错误，并做必要的标点规范；不要更改语法：

{context}当前需要纠错的字幕：
{combined_content}

要求：
1. 仅修正听写/拼写错误与必要标点，不要更改语法，不要改变原意
2. 保持原有的换行结构和格式
3. 如果有分隔符，请在返回结果中保持相同的分隔符位置
4. 参考上下文信息理解专有名词和语境

请直接返回修正后的文本。"""
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 记录批次信息方便日志定位
        first_entry_num = entries_batch[0].number if entries_batch else batch_start_idx + 1
        batch_size = len(entries_batch)

        for attempt in range(retry_count):
            try:
                response = requests.post(self.api_endpoint, json=data, headers=headers, timeout=self.timeout_seconds)
                response.raise_for_status()
                
                result = response.json()
                corrected_batch = result["choices"][0]["message"]["content"].strip()
                
                # 解析批量结果
                return self._parse_batch_result(corrected_batch, entries_batch)
                
            except requests.exceptions.RequestException as e:
                delay = min(2 ** attempt, MAX_BACKOFF_SECONDS)
                self._log(
                    f"⚠️ 批量API调用失败 (第{attempt + 1}/{retry_count}次，起始序号 {first_entry_num}，本批 {batch_size} 条，超时 {self.timeout_seconds}s): {e}，{delay} 秒后重试",
                    "warning"
                )
                if attempt < retry_count - 1:
                    time.sleep(delay)
                else:
                    self._log(f"⚠️ 批量API调用最终失败: {e}", "error")
                    return [None] * len(entries_batch)
            except (KeyError, IndexError) as e:
                self._log(f"⚠️ 批量API响应格式错误: {e}", "error")
                return [None] * len(entries_batch)
    
    def _parse_batch_result(self, corrected_batch: str, original_entries: List[SRTEntry]) -> List[Optional[str]]:
        """解析批量纠错结果（支持分隔符解析）"""
        results = []
        
        try:
            # 使用分隔符分割结果
            separator = "\n===SUBTITLE_SEPARATOR_{index}===\n"
            corrected_contents = []
            
            for i in range(len(original_entries)):
                if i == 0:
                    # 第一部分没有前置分隔符
                    if len(original_entries) > 1:
                        parts = corrected_batch.split(separator.format(index=1), 1)
                        if len(parts) > 0:
                            corrected_contents.append(parts[0].strip())
                        if len(parts) > 1:
                            remaining = parts[1]
                        else:
                            remaining = ""
                    else:
                        # 只有一条字幕
                        corrected_contents.append(corrected_batch.strip())
                        remaining = ""
                else:
                    # 后续部分
                    if i < len(original_entries) - 1:
                        # 不是最后一个，继续分割
                        parts = remaining.split(separator.format(index=i+1), 1)
                        if len(parts) > 0:
                            corrected_contents.append(parts[0].strip())
                        if len(parts) > 1:
                            remaining = parts[1]
                        else:
                            remaining = ""
                    else:
                        # 最后一个，取剩余所有内容
                        corrected_contents.append(remaining.strip())
            
            # 清理和验证结果
            for i, (entry, corrected_text) in enumerate(zip(original_entries, corrected_contents)):
                if corrected_text:
                    # 清理结果
                    cleaned_text = self._clean_corrected_text(corrected_text, entry.content)
                    results.append(cleaned_text)
                else:
                    # 如果没有找到对应结果，返回原文
                    results.append(entry.content)
            
            # 确保结果数量匹配
            while len(results) < len(original_entries):
                results.append(original_entries[len(results)].content)
                    
        except Exception as e:
            logger.error(f"解析批量结果失败: {e}")
            # 如果解析失败，尝试备用解析方法
            results = self._fallback_parse_result(corrected_batch, original_entries)
        
        return results
    
    def _fallback_parse_result(self, corrected_batch: str, original_entries: List[SRTEntry]) -> List[Optional[str]]:
        """备用解析方法（按行数分割）"""
        try:
            lines = corrected_batch.strip().split('\n')
            
            # 简单按条目数量平均分配
            entries_count = len(original_entries)
            lines_per_entry = max(1, len(lines) // entries_count)
            
            results = []
            for i in range(entries_count):
                start_idx = i * lines_per_entry
                if i == entries_count - 1:
                    # 最后一个条目取剩余所有行
                    end_idx = len(lines)
                else:
                    end_idx = start_idx + lines_per_entry
                
                entry_lines = lines[start_idx:end_idx]
                corrected_text = '\n'.join(entry_lines).strip()
                
                if corrected_text:
                    results.append(self._clean_corrected_text(corrected_text, original_entries[i].content))
                else:
                    results.append(original_entries[i].content)
            
            return results
            
        except Exception as e:
            logger.error(f"备用解析也失败: {e}")
            # 最后的备份：返回原文
            return [entry.content for entry in original_entries]
    
    def correct_text_with_context(self, text: str, context_entries: List[SRTEntry] = None, retry_count: int = MAX_API_RETRIES) -> Optional[str]:
        """使用API纠错文本（支持上下文感知）"""
        # 构建用户消息（强调不要更改语法）
        user_message = f"请修正以下字幕中的听写/拼写错误，并做必要的标点规范；不要更改语法：\n\n{text}"
        
        # 如果有上下文，添加到消息中
        if context_entries and len(context_entries) > 0:
            context_text = "\n".join([f"字幕{entry.number}: {entry.content}" for entry in context_entries])
            user_message = f"上下文字幕：\n{context_text}\n\n当前需要纠错的字幕：\n{text}\n\n请结合上下文，仅修正听写/拼写错误与必要标点；不要更改语法。"
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(retry_count):
            try:
                response = requests.post(self.api_endpoint, json=data, headers=headers, timeout=self.timeout_seconds)
                response.raise_for_status()
                
                result = response.json()
                corrected_text = result["choices"][0]["message"]["content"].strip()
                
                # 清理可能的格式问题
                corrected_text = self._clean_corrected_text(corrected_text, text)
                
                return corrected_text
                
            except requests.exceptions.RequestException as e:
                delay = min(2 ** attempt, MAX_BACKOFF_SECONDS)
                self._log(
                    f"⚠️ API调用失败 (第{attempt + 1}/{retry_count}次): {e}，{delay} 秒后重试",
                    "warning"
                )
                if attempt < retry_count - 1:
                    time.sleep(delay)  # 退避等待
                else:
                    self._log(f"⚠️ API调用最终失败: {e}", "error")
                    return None
            except (KeyError, IndexError) as e:
                self._log(f"⚠️ API响应格式错误: {e}", "error")
                return None
    
    def _clean_corrected_text(self, corrected_text: str, original_text: str) -> str:
        """清理纠错后的文本，确保格式正确"""
        # 移除可能的引号或多余的空白
        corrected_text = corrected_text.strip()
        
        # 如果AI返回了引号包围的文本，去除引号
        if (corrected_text.startswith('"') and corrected_text.endswith('"')) or \
           (corrected_text.startswith("'") and corrected_text.endswith("'")):
            corrected_text = corrected_text[1:-1].strip()
        
        # 如果AI返回了说明性文字，尝试提取实际内容
        if "修正后的文本" in corrected_text or "纠错结果" in corrected_text or "主要修正" in corrected_text:
            lines = corrected_text.split('\n')
            for line in lines:
                line = line.strip()
                if line and not any(keyword in line for keyword in ["修正", "纠错", "原文", "结果", "主要"]):
                    corrected_text = line
                    break
        
        # 保持原文的换行结构
        original_lines = original_text.strip().split('\n')
        corrected_lines = corrected_text.strip().split('\n')
        
        # 如果修正后的行数与原文不同，尝试调整
        if len(original_lines) > 1 and len(corrected_lines) == 1:
            # 如果原文是多行但修正后变成单行，尝试按原文长度分割
            if len(corrected_text) > len(original_text) * 0.8:  # 长度相近时才分割
                mid = len(corrected_text) // 2
                corrected_text = corrected_text[:mid].strip() + '\n' + corrected_text[mid:].strip()
        
        return corrected_text

class SubtitleFormatter:
    """字幕格式规范化处理器"""
    
    def __init__(self, format_options: dict = None):
        """
        初始化格式化器
        format_options: 格式化选项字典
        """
        self.format_options = format_options or {
            'clean_newlines': True,    # 清理多余换行和合并过短行
            'remove_spaces': True,     # 移除多余空格  
            'normalize_punctuation': True,   # 统一标点格式
            'smart_line_break': True,  # 智能换行（避免单行过长）
        }
    
    def format_subtitle_content(self, content: str) -> str:
        """对单条字幕内容进行格式规范化"""
        if not content:
            return content
            
        formatted_content = content
        
        # 1. 清理多余换行和合并过短行
        if self.format_options.get('clean_newlines', True):
            formatted_content = self._clean_extra_newlines(formatted_content)
        
        # 2. 移除多余空格
        if self.format_options.get('remove_spaces', True):
            formatted_content = self._remove_extra_spaces(formatted_content)
        
        # 3. 统一标点格式
        if self.format_options.get('normalize_punctuation', True):
            formatted_content = self._normalize_punctuation(formatted_content)
        
        # 4. 智能换行（避免单行过长）
        if self.format_options.get('smart_line_break', True):
            formatted_content = self._smart_line_break(formatted_content)
        
        return formatted_content.strip()
    
    def _clean_extra_newlines(self, text: str) -> str:
        """清理所有换行符，将多行字幕合并为单行"""
        # 移除所有换行符，将多行内容合并为一行
        lines = text.split('\n')
        
        # 清理每行并过滤空行
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:  # 只保留非空行
                cleaned_lines.append(line)
        
        # 用空格连接所有行，形成单行字幕
        return ' '.join(cleaned_lines)
    
    def _remove_extra_spaces(self, text: str) -> str:
        """移除多余的空格"""
        lines = text.split('\n')
        cleaned_lines = []
        cjk_chars = '\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af'
        
        for line in lines:
            # 移除行首行尾空格
            line = line.strip()
            # 将各种空白字符折叠为单个ASCII空格（不包含换行）
            line = re.sub(r'\s+', ' ', line)
            # 移除中日韩文字之间的空格（保留英文单词间空格）
            line = re.sub(rf'(?<=[{cjk_chars}]) +(?=[{cjk_chars}])', '', line)
            if line:  # 只保留非空行
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def _normalize_punctuation(self, text: str) -> str:
        """统一标点符号格式"""
        # 移除标点符号前的空格
        text = re.sub(r' +([，。！？；：、])', r'\1', text)
        # 仅在标点后紧跟英文/数字时插入空格（避免中文标点后强行加空格）
        text = re.sub(r'([，。！？；：、])([A-Za-z0-9])', r'\1 \2', text)
        # 处理引号的空格
        text = re.sub(r' +"', r'"', text)  # 引号前不要空格
        text = re.sub(r'" +', r'"', text)   # 引号后不要空格
        return text
    
    def _smart_line_break(self, text: str, max_line_length: int = 35) -> str:
        """智能换行，避免单行过长影响字幕显示效果"""
        lines = text.split('\n')
        result_lines = []
        
        for line in lines:
            if len(line) <= max_line_length:
                result_lines.append(line)
                continue
            
            # 对过长的行进行智能换行
            broken_lines = self._break_long_line(line, max_line_length)
            result_lines.extend(broken_lines)
        
        return '\n'.join(result_lines)
    
    def _break_long_line(self, line: str, max_length: int) -> list:
        """将单行过长的内容智能断行"""
        if len(line) <= max_length:
            return [line]
        
        # 定义断行优先级（从高到低）
        break_points = [
            r'([。！？])([^"）】])',  # 句号、感叹号、问号后（但不在引号、括号前）
            r'([，；：])([^"）】])',   # 逗号、分号、冒号后
            r'([、])([^"）】])',      # 顿号后
            r'(["])([^）】])',       # 引号后
            r'([）】])([^，。！？；：])', # 右括号后（但不在标点前）
        ]
        
        result = []
        remaining = line
        
        while len(remaining) > max_length:
            best_break = -1
            
            # 寻找最佳断行点
            for pattern in break_points:
                matches = list(re.finditer(pattern, remaining))
                for match in matches:
                    break_pos = match.start() + len(match.group(1))
                    # 确保断行点在合理范围内（不要太早或太晚断行）
                    if max_length * 0.6 <= break_pos <= max_length:
                        best_break = break_pos
                        break
                if best_break != -1:
                    break
            
            if best_break != -1:
                # 在最佳断行点断行
                current_line = remaining[:best_break].strip()
                remaining = remaining[best_break:].strip()
                
                # 避免产生太短的行
                if len(current_line) >= 8:  # 最短8个字符
                    result.append(current_line)
                else:
                    # 如果断行后的行太短，与下一行合并
                    if result:
                        result[-1] += ' ' + current_line
                    else:
                        remaining = current_line + ' ' + remaining
                        break
            else:
                # 没有找到合适的断行点，强制在最大长度处断行
                # 但要避免在标点符号前断行
                break_pos = max_length
                while break_pos > max_length * 0.8 and break_pos > 0:
                    if remaining[break_pos-1] not in '，。！？；：、"（）【】':
                        break
                    break_pos -= 1
                
                if break_pos <= max_length * 0.8:
                    break_pos = max_length
                
                current_line = remaining[:break_pos].strip()
                remaining = remaining[break_pos:].strip()
                
                if len(current_line) >= 8:
                    result.append(current_line)
                else:
                    if result:
                        result[-1] += ' ' + current_line
                    else:
                        break
        
        # 添加剩余内容
        if remaining.strip():
            remaining = remaining.strip()
            # 如果剩余内容太短，尝试与上一行合并
            if len(remaining) <= 6 and result and len(result[-1]) + len(remaining) <= max_length * 1.2:
                result[-1] += ' ' + remaining
            else:
                result.append(remaining)
        
        return result if result else [line]

class SRTCorrector:
    """SRT字幕纠错器"""
    def __init__(self, api: CorrectionAPI, batch_size: int = 5, threads: int = 3, format_options: dict = None, 
                 output_callback=None, context_window: int = 2, use_true_batch: bool = False):
        self.api = api
        self.batch_size = batch_size
        self.threads = threads
        self.formatter = SubtitleFormatter(format_options)
        self.output_callback = output_callback  # GUI输出回调
        self.context_window = context_window  # 上下文窗口大小
        self.use_true_batch = use_true_batch  # 是否使用真批量模式
        self.stats = {
            'total_entries': 0,
            'corrected_entries': 0,
            'error_entries': 0,
            'unchanged_entries': 0,
            'formatted_entries': 0
        }
    
    def _log_and_output(self, message: str, level: str = "info"):
        """同时写入日志和GUI输出"""
        # 写入日志文件
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        
        # 发送到GUI（如果有回调）
        if self.output_callback:
            self.output_callback(message)
    
    def parse_srt_file(self, file_path: str) -> List[SRTEntry]:
        """解析SRT文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
        
        entries = []
        for match in SRT_PATTERN.finditer(content):
            number = int(match.group(1))
            start_time = match.group(2)
            end_time = match.group(3)
            subtitle_content = match.group(4).strip()
            
            entries.append(SRTEntry(number, start_time, end_time, subtitle_content))
        
        self._log_and_output(f"📄 成功解析字幕文件，共发现 {len(entries)} 条字幕")
        return entries
    
    def correct_subtitle_entry(self, entry: SRTEntry, context_entries: List[SRTEntry] = None) -> SRTEntry:
        """纠错单个字幕条目（两阶段处理，支持上下文感知）"""
        original_content = entry.content
        
        # 第一阶段：编程方式的格式规范化
        formatted_content = self.formatter.format_subtitle_content(original_content)
        
        # 检查格式化是否有改变
        format_changed = formatted_content != original_content
        if format_changed:
            self.stats['formatted_entries'] += 1
            self._log_and_output(f"🔧 第{entry.number}条 - 格式已整理")
        
        # 检查是否需要AI纠错（跳过纯英文、数字或符号）
        if not self._needs_correction(formatted_content):
            self.stats['unchanged_entries'] += 1
            # 如果只有格式化改变，也算作处理过的条目
            if format_changed:
                return SRTEntry(entry.number, entry.start_time, entry.end_time, formatted_content)
            return entry
        
        # 第二阶段：AI模型纠错和优化（带上下文）
        self._log_and_output(f"⏳ 正在AI纠错第{entry.number}条...")
        corrected_content = self.api.correct_text_with_context(formatted_content, context_entries)
        
        if corrected_content is None:
            self._log_and_output(f"⚠️ 第{entry.number}条 - AI纠错失败，保留格式化结果", "warning")
            self.stats['error_entries'] += 1
            # 返回格式化后的内容，即使AI失败也比原始内容好
            return SRTEntry(entry.number, entry.start_time, entry.end_time, formatted_content)
        
        # 检查AI纠错是否有实际改变
        if corrected_content.strip() == formatted_content.strip():
            self.stats['unchanged_entries'] += 1
        else:
            self.stats['corrected_entries'] += 1
            # 只显示改变的内容，让日志更简洁
            original_preview = formatted_content[:20] + "..." if len(formatted_content) > 20 else formatted_content
            corrected_preview = corrected_content[:20] + "..." if len(corrected_content) > 20 else corrected_content
            self._log_and_output(f"🤖 第{entry.number}条 - 已纠错: 「{original_preview}」→「{corrected_preview}」")
        
        return SRTEntry(entry.number, entry.start_time, entry.end_time, corrected_content)
    
    def _needs_correction(self, text: str) -> bool:
        """判断文本是否需要纠错"""
        # 检测是否包含有意义的文字内容（中文、英文、日文、韩文等）
        # 跳过纯数字、纯符号的内容
        
        # 中文字符
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        # 英文字母
        english_chars = re.findall(r'[a-zA-Z]', text)
        # 日文字符（平假名+片假名）
        japanese_chars = re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text)
        # 韩文字符
        korean_chars = re.findall(r'[\uac00-\ud7af]', text)
        
        # 如果包含任何语言的文字字符，就需要纠错
        return len(chinese_chars) > 0 or len(english_chars) > 0 or len(japanese_chars) > 0 or len(korean_chars) > 0
    
    def _get_context_entries(self, entries: List[SRTEntry], current_index: int) -> List[SRTEntry]:
        """获取当前字幕条目的上下文"""
        context_entries = []
        start_index = max(0, current_index - self.context_window)
        end_index = min(len(entries), current_index + self.context_window + 1)
        
        for i in range(start_index, end_index):
            if i != current_index:  # 排除当前条目本身
                context_entries.append(entries[i])
        
        return context_entries
    
    def _process_true_batch_mode(self, batches, corrected_entries, progress_callback, all_entries=None):
        """真批量模式处理（支持上下文感知）"""
        total_batches = len(batches)
        
        # 初始化完成计数和锁
        completed_batches = 0
        completed_batches_lock = threading.Lock()
        
        # 使用线程池并发处理批次
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.threads) as executor:
            # 提交所有批次任务
            future_to_batch_idx = {}
            batch_results = {}
            
            for batch_idx, batch in enumerate(batches):
                future = executor.submit(self._process_single_true_batch, batch_idx, batch, all_entries)
                future_to_batch_idx[future] = batch_idx
            
            # 收集批次结果并实时更新进度
            for future in concurrent.futures.as_completed(future_to_batch_idx):
                batch_idx = future_to_batch_idx[future]
                try:
                    result = future.result()
                    batch_results[batch_idx] = result
                except Exception as e:
                    self._log_and_output(f"❌ 第{batch_idx + 1}批处理失败: {str(e)}", "error")
                    # 添加原始批次条目
                    batch_results[batch_idx] = batches[batch_idx]
                    for entry in batches[batch_idx]:
                        self.stats['error_entries'] += 1
                
                # 更新完成计数和进度
                with completed_batches_lock:
                    completed_batches += 1
                    progress = completed_batches / total_batches
                    if progress_callback:
                        progress_callback(progress, f"已完成 {completed_batches}/{total_batches} 批")
                    self._log_and_output(f"📦 完成第 {completed_batches}/{total_batches} 批次")
            
            # 按顺序合并结果
            for batch_idx in range(total_batches):
                if batch_idx in batch_results:
                    corrected_entries.extend(batch_results[batch_idx])
    
    def _process_single_true_batch(self, batch_idx, batch, all_entries=None):
        """处理单个批次（用于真批量模式的并发执行）"""
        corrected_batch_entries = []
        
        try:
            # 首先对批次中的所有条目进行格式规范化
            formatted_batch = []
            for entry in batch:
                formatted_content = self.formatter.format_subtitle_content(entry.content)
                if formatted_content != entry.content:
                    self.stats['formatted_entries'] += 1
                    self._log_and_output(f"🔧 第{entry.number}条 - 格式已整理")
                formatted_entry = SRTEntry(entry.number, entry.start_time, entry.end_time, formatted_content)
                formatted_batch.append(formatted_entry)
            
            # 过滤出需要AI纠错的条目
            need_correction = []
            no_correction_needed = []
            for entry in formatted_batch:
                if self._needs_correction(entry.content):
                    need_correction.append(entry)
                else:
                    no_correction_needed.append(entry)
                    self.stats['unchanged_entries'] += 1
            
            # 批量调用API纠错（强化错误处理，支持上下文）
            if need_correction:
                context_info = f" (带上下文)" if self.context_window > 0 and all_entries else ""
                self._log_and_output(f"🤖 批量纠错第{batch_idx + 1}批: {len(need_correction)}条字幕{context_info}")
                
                # 计算当前批次在全部条目中的起始位置
                batch_start_idx = batch_idx * self.batch_size
                
                # 多次重试机制
                corrected_results = None
                for attempt in range(MAX_BATCH_RETRIES):
                    try:
                        # 添加等待API响应的提示
                        self._log_and_output(
                            f"⏳ 正在等待AI响应第{batch_idx + 1}批数据... (尝试 {attempt + 1}/{MAX_BATCH_RETRIES})"
                        )
                        corrected_results = self.api.correct_batch_texts(need_correction, all_entries, batch_start_idx, self.context_window)
                        valid_length = corrected_results and len(corrected_results) == len(need_correction)
                        has_valid = valid_length and any(res is not None for res in corrected_results)
                        if valid_length and has_valid:
                            break

                        reason = "批量结果数量不匹配" if not valid_length else "批量结果为空"
                        self._log_and_output(
                            f"⚠️ {reason}，重试第{attempt + 1}/{MAX_BATCH_RETRIES}次",
                            "warning"
                        )
                    except Exception as e:
                        self._log_and_output(
                            f"⚠️ 批量API调用失败 (第{attempt + 1}/{MAX_BATCH_RETRIES}次): {str(e)}",
                            "warning"
                        )
                        if attempt == MAX_BATCH_RETRIES - 1:  # 最后一次重试失败
                            self._log_and_output("❌ 批量处理失败，保持批量模式：本批将保留格式化结果", "warning")
                            corrected_results = [None] * len(need_correction)
                
                # 处理批量结果（不自动回退到逐条处理）
                if not corrected_results or len(corrected_results) != len(need_correction):
                    corrected_results = [None] * len(need_correction)

                if corrected_results:
                    for entry, corrected_text in zip(need_correction, corrected_results):
                        if corrected_text is not None:
                            if corrected_text.strip() != entry.content.strip():
                                self.stats['corrected_entries'] += 1
                                original_preview = entry.content[:20] + "..." if len(entry.content) > 20 else entry.content
                                corrected_preview = corrected_text[:20] + "..." if len(corrected_text) > 20 else corrected_text
                                self._log_and_output(f"🤖 第{entry.number}条 - 已纠错: 「{original_preview}」→「{corrected_preview}」")
                            else:
                                self.stats['unchanged_entries'] += 1
                            
                            corrected_entry = SRTEntry(entry.number, entry.start_time, entry.end_time, corrected_text)
                            corrected_batch_entries.append(corrected_entry)
                        else:
                            self._log_and_output(f"⚠️ 第{entry.number}条 - AI纠错失败，保留格式化结果", "warning")
                            self.stats['error_entries'] += 1
                            corrected_batch_entries.append(entry)
            
            # 添加不需要纠错的条目
            corrected_batch_entries.extend(no_correction_needed)
            
        except Exception as e:
            self._log_and_output(f"❌ 第{batch_idx + 1}批处理失败: {str(e)}", "error")
            # 返回原始批次条目
            corrected_batch_entries.extend(batch)
            for entry in batch:
                self.stats['error_entries'] += 1
        
        return corrected_batch_entries

    def _process_individual_mode(self, batches, corrected_entries, progress_callback):
        """逐条处理模式（原来的伪批量模式）"""
        total_batches = len(batches)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.threads) as executor:
            for batch_idx, batch in enumerate(batches):
                # 提交批次中的所有任务（强化错误处理）
                future_to_entry = {}
                for entry in batch:
                    future = executor.submit(self._correct_single_entry_with_retry, entry)
                    future_to_entry[future] = entry
                
                # 收集批次结果
                batch_results = []
                for future in concurrent.futures.as_completed(future_to_entry):
                    entry = future_to_entry[future]
                    try:
                        corrected_entry = future.result()
                        batch_results.append(corrected_entry)
                    except Exception as e:
                        self._log_and_output(f"❌ 第{entry.number}条处理失败: {str(e)}", "error")
                        batch_results.append(entry)  # 保持原文
                        self.stats['error_entries'] += 1
                
                # 按序号排序并添加到结果列表
                batch_results.sort(key=lambda x: x.number)
                corrected_entries.extend(batch_results)
                
                # 更新进度
                progress = (batch_idx + 1) / total_batches
                if progress_callback:
                    progress_callback(progress, f"已完成 {batch_idx + 1}/{total_batches} 批")
                
                self._log_and_output(f"📦 完成第 {batch_idx + 1}/{total_batches} 批次")

    def _correct_single_entry_with_retry(self, entry: SRTEntry) -> SRTEntry:
        """带重试机制的单条字幕纠错"""
        for attempt in range(MAX_ENTRY_RETRIES):  # 最多重试MAX_ENTRY_RETRIES次
            try:
                return self.correct_subtitle_entry(entry)
            except Exception as e:
                if attempt == MAX_ENTRY_RETRIES - 1:  # 最后一次重试
                    self._log_and_output(
                        f"⚠️ 第{entry.number}条重试{MAX_ENTRY_RETRIES}次后仍失败: {str(e)}",
                        "warning"
                    )
                    raise e
                else:
                    self._log_and_output(
                        f"⚠️ 第{entry.number}条处理失败，重试第{attempt + 1}/{MAX_ENTRY_RETRIES}次",
                        "warning"
                    )
                    time.sleep(1)  # 等待1秒后重试

    def _fallback_individual_correction(self, entries: List[SRTEntry]) -> List[Optional[str]]:
        """批量失败时的逐条纠错回退方案"""
        results = []
        for entry in entries:
            try:
                corrected_text = self.api.correct_text_with_context(entry.content, None)
                results.append(corrected_text)
            except Exception as e:
                self._log_and_output(f"⚠️ 回退纠错第{entry.number}条也失败: {str(e)}", "warning")
                results.append(entry.content)  # 返回原文
        return results
    
    def correct_srt_file(self, input_file: str, output_file: str, progress_callback=None) -> bool:
        """纠错整个SRT文件"""
        try:
            self._log_and_output(f"🚀 开始处理字幕文件")
            self._log_and_output(f"📂 输入: {input_file}")
            self._log_and_output(f"📝 输出: {output_file}")
            
            # 解析输入文件
            entries = self.parse_srt_file(input_file)
            if not entries:
                self._log_and_output("❌ 未发现有效字幕内容", "error")
                return False
            
            self.stats['total_entries'] = len(entries)
            corrected_entries = []
            
            # 分批处理
            batches = [entries[i:i + self.batch_size] for i in range(0, len(entries), self.batch_size)]
            total_batches = len(batches)
            
            if self.batch_size < len(entries):
                self._log_and_output(f"📦 将分{total_batches}批次处理，每批最多{self.batch_size}条字幕")
            
            # 根据用户选择使用不同的批量模式
            if self.use_true_batch:
                self._log_and_output("⚡ 启用真批量模式 (快速高效)")
                if self.context_window > 0:
                    self._log_and_output("🧠 真批量模式支持上下文感知")
                self._process_true_batch_mode(batches, corrected_entries, progress_callback, entries)
            elif self.context_window > 0:
                # 使用上下文感知的顺序处理（保证上下文的准确性）
                self._log_and_output(f"🧠 启用上下文感知模式 (前后各{self.context_window}条字幕作为参考)")
                
                for i, entry in enumerate(entries):
                    try:
                        # 获取当前条目的上下文
                        context_entries = self._get_context_entries(entries, i)
                        
                        # 纠错当前条目
                        corrected_entry = self.correct_subtitle_entry(entry, context_entries)
                        corrected_entries.append(corrected_entry)
                        
                        # 更新进度
                        progress = (i + 1) / len(entries)
                        if progress_callback:
                            progress_callback(progress, f"已完成 {i + 1}/{len(entries)} 条字幕")
                        
                        if (i + 1) % 10 == 0:  # 每10条输出一次进度
                            self._log_and_output(f"⏳ 进度更新: 已完成 {i + 1}/{len(entries)} 条字幕")
                            
                    except Exception as e:
                        self._log_and_output(f"❌ 第{entry.number}条处理失败: {str(e)}", "error")
                        corrected_entries.append(entry)  # 保持原文
                        self.stats['error_entries'] += 1
            else:
                self._log_and_output("🔧 启用逐条处理模式 (稳定准确)")
                self._process_individual_mode(batches, corrected_entries, progress_callback)
            
            # 按序号排序结果
            corrected_entries.sort(key=lambda x: x.number)
            
            # 写入输出文件
            self._write_srt_file(corrected_entries, output_file)
            
            # 打印统计信息
            self._print_stats()
            
            self._log_and_output(f"✅ 字幕纠错完成！")
            self._log_and_output(f"📁 文件已保存: {output_file}")
            return True
            
        except Exception as e:
            self._log_and_output(f"💥 处理过程出现异常: {str(e)}", "error")
            return False
    
    def _write_srt_file(self, entries: List[SRTEntry], output_file: str):
        """写入SRT文件"""
        with open(output_file, 'w', encoding='utf-8') as f:
            for i, entry in enumerate(entries):
                f.write(entry.to_string())
                if i < len(entries) - 1:  # 不是最后一个条目
                    f.write('\n')
    
    def _print_stats(self):
        """打印统计信息"""
        self._log_and_output("")
        self._log_and_output("📊 处理结果统计")
        self._log_and_output("─" * 30)
        self._log_and_output(f"📝 总计字幕条目: {self.stats['total_entries']} 条")
        self._log_and_output(f"🔧 格式已整理: {self.stats['formatted_entries']} 条")
        self._log_and_output(f"🤖 AI已纠错: {self.stats['corrected_entries']} 条")
        self._log_and_output(f"✨ 无需修改: {self.stats['unchanged_entries']} 条")
        
        if self.stats['error_entries'] > 0:
            self._log_and_output(f"⚠️ 处理失败: {self.stats['error_entries']} 条")
        
        if self.stats['total_entries'] > 0:
            format_rate = (self.stats['formatted_entries'] / self.stats['total_entries']) * 100
            correction_rate = (self.stats['corrected_entries'] / self.stats['total_entries']) * 100
            self._log_and_output("─" * 30)
            self._log_and_output(f"🔧 格式整理率: {format_rate:.1f}%")
            self._log_and_output(f"🤖 AI纠错率: {correction_rate:.1f}%")
            
            # 计算总改进率
            improved_entries = self.stats['formatted_entries'] + self.stats['corrected_entries']
            improve_rate = (improved_entries / self.stats['total_entries']) * 100
            self._log_and_output(f"🎯 总改进率: {improve_rate:.1f}%")

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="SRT字幕纠错工具")
    parser.add_argument("input_file", help="输入SRT文件路径")
    parser.add_argument("output_file", help="输出SRT文件路径")
    parser.add_argument("--api-key", required=True, help="API密钥")
    parser.add_argument("--api-endpoint", required=True, help="API端点URL")
    parser.add_argument("--model", required=True, help="模型名称")
    parser.add_argument("--batch-size", type=int, default=5, help="批次大小 (默认: 5)")
    parser.add_argument("--threads", type=int, default=3, help="并发线程数 (默认: 3)")
    parser.add_argument("--temperature", type=float, default=0.3, help="温度参数 (默认: 0.3)")
    
    args = parser.parse_args()
    
    # 检查输入文件
    if not os.path.exists(args.input_file):
        logger.error(f"输入文件不存在: {args.input_file}")
        return 1
    
    # 创建API实例
    api = CorrectionAPI(
        api_type="custom",
        api_key=args.api_key,
        api_endpoint=args.api_endpoint,
        model=args.model,
        temperature=args.temperature
    )
    
    # 创建纠错器实例
    corrector = SRTCorrector(api, args.batch_size, args.threads)
    
    # 执行纠错
    success = corrector.correct_srt_file(args.input_file, args.output_file)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
