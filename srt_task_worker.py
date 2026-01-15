#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class CorrectorJobConfig:
    input_file: str
    output_file: str
    api_key: str
    api_endpoint: str
    model: str
    batch_size: int
    threads: int
    temperature: float
    timeout_seconds: int
    user_prompt: str
    format_options: Dict[str, bool]
    ai_options: Dict[str, bool]
    context_window: int
    use_true_batch: bool


@dataclass(frozen=True)
class PolisherJobConfig:
    input_file: str
    output_file: str
    api_type: str
    api_key: str
    api_endpoint: str
    model: str
    batch_size: int
    context_size: int
    threads: int
    temperature: float
    user_prompt: str
    length_policy: str
    corner_quotes: bool
    resume: bool = True
    auto_verify: bool = True


def _make_queue_log_handler(out_queue, channel: str):
    import logging

    class _QueueLogHandler(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.INFO)

        def emit(self, record):
            try:
                msg = self.format(record)
                out_queue.put((channel, msg))
            except Exception:
                pass

    return _QueueLogHandler()


@dataclass(frozen=True)
class TranslationJobConfig:
    input_file: str
    output_file: str
    api_type: str
    api_key: str
    api_endpoint: str
    model: str
    batch_size: int
    context_size: int
    threads: int
    temperature: float
    user_prompt: str
    resume: bool
    bilingual: bool
    start_num: Optional[int] = None
    end_num: Optional[int] = None
    literal_align: bool = False
    structured_output: bool = False
    professional_mode: bool = False


@dataclass(frozen=True)
class CheckerJobConfig:
    source_file: str
    translated_file: str
    report_file: str


def run_corrector_job(config: CorrectorJobConfig, out_queue) -> None:
    try:
        from srt_corrector import CorrectionAPI, SRTCorrector

        def output_callback(message: str):
            try:
                out_queue.put(("corrector", str(message)))
            except Exception:
                pass

        api = CorrectionAPI(
            api_type="custom",
            api_key=config.api_key,
            api_endpoint=config.api_endpoint,
            model=config.model,
            temperature=config.temperature,
            timeout_seconds=config.timeout_seconds,
            log_callback=output_callback,
        )

        # 根据AI选项修改系统提示词
        ai_enhancements = []
        if not config.ai_options.get("smart_spacing", True):
            ai_enhancements.append("不要添加中英文之间的空格")
        if not config.ai_options.get("smart_punctuation", True):
            ai_enhancements.append("不要优化标点符号")
        if not config.ai_options.get("fluency_optimization", True):
            ai_enhancements.append("不要优化语法流畅度")
        if ai_enhancements:
            api.system_prompt = api.system_prompt + f"\n\n特别注意：{'; '.join(ai_enhancements)}。"
        if config.user_prompt:
            api.system_prompt = api.system_prompt + f"\n\n用户额外要求：{config.user_prompt}"

        corrector = SRTCorrector(
            api,
            config.batch_size,
            config.threads,
            config.format_options or {},
            output_callback,
            config.context_window,
            config.use_true_batch,
        )

        def progress_callback(progress: float, message: str):
            try:
                p = float(progress)
            except Exception:
                p = 0.0
            if p < 0:
                p = 0.0
            if p > 1:
                p = 1.0
            out_queue.put(("corrector_progress", p, str(message or "")))

        out_queue.put(("corrector", "开始字幕纠错...\n"))
        ok = bool(corrector.correct_srt_file(config.input_file, config.output_file, progress_callback))
        out_queue.put(("corrector_done", ok, config.input_file, config.output_file))
    except Exception as e:
        try:
            out_queue.put(("corrector_error", str(e)))
        except Exception:
            pass


def run_polisher_job(config: PolisherJobConfig, out_queue) -> None:
    try:
        import logging

        from srt_polisher import SRTPolisher

        polisher_logger = logging.getLogger("SRT-Polisher")
        polisher_logger.setLevel(logging.INFO)

        # 将润色器日志透传到GUI（避免依赖控制台）
        handler = _make_queue_log_handler(out_queue, "polisher")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        polisher_logger.addHandler(handler)
        polisher_logger.propagate = False

        polisher = SRTPolisher(
            api_type=config.api_type,
            api_key=config.api_key,
            batch_size=config.batch_size,
            context_size=config.context_size,
            max_workers=config.threads,
            model_name=config.model or None,
            temperature=config.temperature,
            user_prompt=config.user_prompt,
            api_endpoint=config.api_endpoint if config.api_type == "custom" else None,
            length_policy=config.length_policy,
            fallback_on_timecode=False,
            corner_quotes=config.corner_quotes,
        )

        out_queue.put(("polisher", "[INFO] 开始润色...\n"))
        ok = bool(polisher.polish_srt_file(config.input_file, config.output_file, resume=config.resume, auto_verify=config.auto_verify))
        summary: Optional[Dict[str, Any]] = getattr(polisher, "last_verify_summary", None)
        out_queue.put(("polisher_done", ok, config.input_file, config.output_file, summary))
    except Exception as e:
        try:
            out_queue.put(("polisher_error", str(e)))
        except Exception:
            pass


def run_translation_job(config: TranslationJobConfig, out_queue) -> None:
    try:
        import logging

        import srt_translator as st

        # Ensure custom endpoint visible inside module
        if config.api_type == "custom" and config.api_endpoint:
            try:
                st.API_ENDPOINTS["custom"] = config.api_endpoint
            except Exception:
                pass
        if config.model:
            try:
                st.DEFAULT_MODELS[config.api_type] = config.model
            except Exception:
                pass

        logger = logging.getLogger("SRT-Translator")
        logger.setLevel(logging.INFO)
        handler = _make_queue_log_handler(out_queue, "translation")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False

        translator = st.SRTTranslator(
            config.api_type,
            config.api_key,
            config.batch_size,
            config.context_size,
            config.threads,
            config.model or None,
            config.user_prompt or "",
            config.bilingual,
            config.temperature,
            literal_align=config.literal_align,
            structured_output=config.structured_output,
            professional_mode=config.professional_mode,
        )

        translator.translate_srt_file(
            config.input_file,
            config.output_file,
            resume=config.resume,
            start_num=config.start_num,
            end_num=config.end_num,
        )
        out_queue.put(("translation_done", True, config.input_file, config.output_file))
    except Exception as e:
        try:
            out_queue.put(("translation_error", str(e)))
            out_queue.put(("translation_done", False, config.input_file, config.output_file))
        except Exception:
            pass


def run_checker_job(config: CheckerJobConfig, out_queue) -> None:
    try:
        import os

        # Disable console logging for checker in GUI-run worker
        os.environ["SRT_SUPPRESS_CONSOLE_LOG"] = "1"

        import io
        from contextlib import redirect_stderr, redirect_stdout

        import srt_checker

        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            ok = bool(
                srt_checker.check_srt_files(
                    config.source_file,
                    config.translated_file,
                    output_file=(config.report_file or None),
                    use_colors=False,
                )
            )
        text = buf.getvalue()
        for line in text.splitlines():
            try:
                if line.strip():
                    out_queue.put(("checking", line))
            except Exception:
                pass

        out_queue.put(("checking_done", ok))
    except Exception as e:
        try:
            out_queue.put(("checking", f"[ERROR] 校验异常: {e}"))
            out_queue.put(("checking_done", False))
        except Exception:
            pass
