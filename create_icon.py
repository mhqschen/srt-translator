#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
创建SRT字幕工具的图标
"""

try:
    from PIL import Image, ImageDraw, ImageFont
    import os
    
    def create_srt_icon(size=256):
        """创建SRT主题的软件图标"""
        # 创建正方形画布
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # 背景渐变色 - 蓝色主题
        for y in range(size):
            color_intensity = int(255 * (1 - y / size * 0.3))
            color = (41, 128, 185, 255)  # 蓝色
            draw.line([(0, y), (size, y)], fill=color)
        
        # 绘制文档样式的背景
        margin = size // 8
        doc_width = size - 2 * margin
        doc_height = size - 2 * margin
        
        # 文档主体 - 白色半透明
        draw.rounded_rectangle(
            [margin, margin, margin + doc_width, margin + doc_height],
            radius=size//20,
            fill=(255, 255, 255, 240),
            outline=(200, 200, 200, 255),
            width=2
        )
        
        # 绘制字幕文本行
        line_height = size // 16
        line_margin = margin + size // 20
        text_width = doc_width - size // 10
        
        # 模拟字幕时间码
        timecode_y = margin + size // 8
        draw.rectangle(
            [line_margin, timecode_y, line_margin + text_width // 3, timecode_y + line_height // 2],
            fill=(52, 152, 219, 180)
        )
        
        # 模拟字幕文本行
        for i, width_ratio in enumerate([0.8, 0.6, 0.9, 0.7]):
            text_y = timecode_y + line_height + i * (line_height // 2 + 2)
            if text_y + line_height // 2 > margin + doc_height - size // 20:
                break
            draw.rectangle(
                [line_margin, text_y, line_margin + int(text_width * width_ratio), text_y + line_height // 3],
                fill=(100, 100, 100, 150)
            )
        
        # 在右下角添加"SRT"文字
        try:
            # 尝试使用系统字体
            font_size = size // 8
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            # 如果找不到字体，使用默认字体
            font = ImageFont.load_default()
        
        # SRT文字
        srt_text = "SRT"
        text_bbox = draw.textbbox((0, 0), srt_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        text_x = size - margin - text_width - size//40
        text_y = size - margin - text_height - size//40
        
        # 文字阴影
        draw.text((text_x + 2, text_y + 2), srt_text, fill=(0, 0, 0, 100), font=font)
        # 主文字
        draw.text((text_x, text_y), srt_text, fill=(255, 255, 255, 255), font=font)
        
        # 添加翻译图标 - 小箭头
        arrow_size = size // 20
        arrow_x = size - margin - arrow_size * 3
        arrow_y = margin + size // 6
        
        # 绘制翻译箭头
        arrow_points = [
            (arrow_x, arrow_y),
            (arrow_x + arrow_size, arrow_y + arrow_size // 2),
            (arrow_x, arrow_y + arrow_size)
        ]
        draw.polygon(arrow_points, fill=(46, 204, 113, 200))
        
        return img
    
    def save_icon():
        """保存多种尺寸的图标"""
        # 创建不同尺寸的图标
        sizes = [16, 32, 48, 64, 128, 256]
        images = []
        
        for size in sizes:
            img = create_srt_icon(size)
            images.append(img)
        
        # 保存为ICO文件
        ico_path = os.path.join(os.path.dirname(__file__), "srt_translator.ico")
        images[0].save(ico_path, format='ICO', sizes=[(img.size[0], img.size[1]) for img in images])
        
        # 也保存一个PNG版本作为预览
        png_path = os.path.join(os.path.dirname(__file__), "srt_translator_icon.png")
        create_srt_icon(256).save(png_path, format='PNG')
        
        print(f"图标已保存: {ico_path}")
        print(f"预览图已保存: {png_path}")
        
        return ico_path, png_path
    
    if __name__ == "__main__":
        save_icon()
        
except ImportError:
    print("需要安装Pillow库: pip install Pillow")
    print("或者可以使用在线图标生成工具创建图标")