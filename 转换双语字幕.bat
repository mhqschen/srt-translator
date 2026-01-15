@echo off
chcp 65001 >nul

rem 设置Python环境变量解决编码问题
set PYTHONIOENCODING=utf-8

echo.
echo =============================================
echo          SRT双语字幕转换工具
echo =============================================
echo.
echo 这个工具可以将您现有的翻译文件转换为双语格式
echo.

rem 检查Python是否安装
echo [INFO] Checking environment...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found, please install Python 3.8+
    echo [INFO] Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

rem 检查是否存在转换脚本
if not exist "independent_bilingual_translator.py" (
    echo [ERROR] Script file not found: independent_bilingual_translator.py
    echo Make sure to run this script in the correct directory
    echo.
    pause
    exit /b 1
)

echo [OK] Environment check completed
echo.

:input_files
echo 请按照提示输入文件路径：
echo.

echo 1. 请拖拽【原始英文字幕文件】到此窗口，然后按回车：
set /p original_file=

echo.
echo 2. 请拖拽【已翻译的字幕文件】到此窗口，然后按回车：
set /p translated_file=

echo.
echo.
echo =============================================
echo 开始转换...
echo =============================================

rem 清理路径中的引号
set original_file=%original_file:"=%
set translated_file=%translated_file:"=%

rem 自动生成输出文件名（在扩展名前添加_双语）
for %%f in ("%translated_file%") do (
    set "output_dir=%%~dpf"
    set "filename=%%~nf"
    set "ext=%%~xf"
)
set "output_file=%output_dir%%filename%_双语%ext%"

rem 检查文件是否存在
if not exist "%original_file%" (
    echo [ERROR] 原始文件不存在！
    echo 文件路径：%original_file%
    echo.
    echo 请检查文件路径是否正确...
    pause
    goto input_files
)

if not exist "%translated_file%" (
    echo [ERROR] 翻译文件不存在！
    echo 文件路径：%translated_file%
    echo.
    echo 请检查文件路径是否正确...
    pause
    goto input_files
)

rem 执行转换
python independent_bilingual_translator.py "%original_file%" "%translated_file%" "%output_file%"

if %errorlevel% equ 0 (
    echo.
    echo [OK] 转换完成！
    echo.
    echo 双语字幕文件已生成：
    echo %output_file%
    echo.
    echo 文件已保存到原文件目录中！
) else (
    echo.
    echo [ERROR] 转换失败！
    echo.
    echo 可能的原因：
    echo - 文件格式不正确
    echo - 字幕条目数量不匹配
    echo - 文件编码问题
)

echo.
echo =============================================
echo 是否要继续转换其他文件？(Y/N)
set /p continue=
if /i "%continue%"=="Y" goto input_files

echo.
echo 感谢使用SRT双语字幕转换工具！
pause