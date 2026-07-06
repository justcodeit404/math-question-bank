"""
用 Qwen-VL 识图，自动定位有图题目的 figure 坐标并裁剪。

用法:
  python detect_figures.py                  # 处理 880题 questions.json 中所有 has_image=true 的题
  python detect_figures.py --id 6           # 只处理 Q6
  python detect_figures.py --dry-run        # 只检测坐标，不裁剪
  python detect_figures.py --book 1000题    # 处理 1000题
  python detect_figures.py --model qwen-vl-max  # 指定模型

需要环境变量: DASHSCOPE_API_KEY
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import dashscope
from dashscope import MultiModalConversation
from PIL import Image

# ── 常量 ──────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
DEFAULT_MODEL = "qwen-vl-plus"

PROMPT_TEMPLATE = """你是一个精确的图像定位助手。

下面是一本考研数学练习册的第 {page} 页的完整扫描图。页面中有多道题目。

**目标题目**：{question_id}
**题目内容**：{question_text}

请你在这张页面图片中，找到属于「{question_id}」这道题的**图片/图形/图表**（通常是坐标系、函数图像、几何图形等），然后返回该图形在图片中的**像素坐标边界框**。

要求：
1. 只返回该题对应的图形，不要包含其他题目的图形
2. 如果该题没有图形（题干中没有"如图"等字样），返回 found: false
3. 坐标格式：[left, top, right, bottom]，像素值

请严格按以下 JSON 格式返回，不要包含其他内容：
```json
{{
  "found": true,
  "bbox": [left, top, right, bottom],
  "description": "简述图形内容"
}}
```
"""


def load_questions_with_images(questions_json):
    """加载 questions.json 中所有 has_image=true 的题目"""
    with open(questions_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    questions = []
    # 兼容两种格式：平铺 list 或 {chapters: [...]} 嵌套
    if isinstance(data, list):
        items = data
    else:
        items = []
        for ch in data.get("chapters", []):
            items.extend(ch.get("questions", []))
    for q in items:
        if q.get("has_image"):
            questions.append(q)
    return questions


def call_qwen_vl(image_path, question_id, question_text, page, model):
    """调用 Qwen-VL 识别图片中的 figure 位置"""
    prompt = PROMPT_TEMPLATE.format(
        page=page,
        question_id=question_id,
        question_text=question_text[:200],
    )

    # 用 base64 编码图片（避免中文路径问题）
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    messages = [
        {
            "role": "user",
            "content": [
                {"image": f"data:image/png;base64,{img_b64}"},
                {"text": prompt},
            ],
        }
    ]

    response = MultiModalConversation.call(model=model, messages=messages)

    if response.status_code != 200:
        print(f"  API 错误: {response.code} - {response.message}")
        return None

    try:
        content = response.output.choices[0].message.content
        if isinstance(content, list):
            text = "".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        else:
            text = str(content)
        return text
    except (KeyError, IndexError, AttributeError) as e:
        print(f"  解析响应失败: {e}")
        return None


def parse_bbox(response_text):
    """从模型回复中提取 JSON 坐标"""
    if not response_text:
        return None
    import re

    text = response_text.strip()
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*"bbox"[^{}]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        print(f"  无法解析 JSON: {text[:200]}")
        return None


def crop_image(image_path, bbox, output_path, padding=20):
    """根据 bbox 裁剪图片"""
    img = Image.open(image_path)
    w, h = img.size
    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(w, right + padding)
    bottom = min(h, bottom + padding)
    cropped = img.crop((left, top, right, bottom))
    cropped.save(output_path)
    return cropped.size


def process_question(q, pdf_images, output_dir, model, dry_run=False):
    """处理单道题目"""
    qid = q["id"]
    page = q.get("page")
    content = q.get("content", "")

    print(f"\n{'='*50}")
    print(f"处理 Q{qid} (page={page})")

    if not page:
        print("  跳过：无 page 信息")
        return None

    image_path = pdf_images / f"page_{page:03d}.png"
    if not image_path.exists():
        print(f"  跳过：页面图片不存在 {image_path}")
        return None

    print(f"  调用 {model} 识别中...")
    response_text = call_qwen_vl(image_path, qid, content, page, model)
    if not response_text:
        print("  失败：无响应")
        return None

    print(f"  模型回复: {response_text[:300]}")

    result = parse_bbox(response_text)
    if not result or not result.get("found"):
        print("  结果：该题没有图形")
        return None

    bbox = result.get("bbox")
    desc = result.get("description", "")
    if not bbox or len(bbox) != 4:
        print(f"  错误：无效的 bbox {bbox}")
        return None

    print(f"  坐标: {bbox}")
    print(f"  描述: {desc}")

    if dry_run:
        print("  [dry-run] 不裁剪")
        return {"id": qid, "page": page, "bbox": bbox, "description": desc}

    output_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"p{page:03d}_q{qid}.png"
    out_path = output_dir / out_name
    size = crop_image(image_path, bbox, out_path)
    print(f"  已保存: {out_path} ({size[0]}x{size[1]})")

    return {
        "id": qid,
        "page": page,
        "bbox": bbox,
        "description": desc,
        "output": out_name,
        "size": list(size),
    }


def main():
    parser = argparse.ArgumentParser(description="用 Qwen-VL 识别有图题目")
    parser.add_argument("--book", default="880题", help="题库目录名 (默认: 880题)")
    parser.add_argument("--id", type=str, help="只处理指定题号")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"模型名 (默认: {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true", help="只检测坐标，不裁剪")
    parser.add_argument("--api-key", type=str, help="DashScope API Key")
    args = parser.parse_args()

    key = args.api_key or os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        print("错误：请设置 DASHSCOPE_API_KEY 环境变量，或用 --api-key 参数")
        sys.exit(1)
    dashscope.api_key = key

    book_dir = PROJECT_ROOT / args.book
    questions_json = book_dir / "questions.json"
    pdf_images = book_dir / "pdf_images"
    output_dir = book_dir / "math-bank" / "images"

    if not questions_json.exists():
        print(f"错误：{questions_json} 不存在")
        sys.exit(1)

    questions = load_questions_with_images(questions_json)
    if args.id:
        questions = [q for q in questions if q["id"] == args.id]
    print(f"题库: {args.book} | 找到 {len(questions)} 道有图题目")

    if not questions:
        print("没有需要处理的题目")
        return

    results = []
    for i, q in enumerate(questions):
        if i > 0:
            time.sleep(1)
        result = process_question(q, pdf_images, output_dir, args.model, args.dry_run)
        if result:
            results.append(result)

    print(f"\n{'='*50}")
    print(f"处理完成：{len(results)}/{len(questions)} 道题成功")
    for r in results:
        print(f"  Q{r['id']}: {r.get('description', '')} → {r.get('output', r.get('bbox', ''))}")

    if results:
        result_path = SCRIPTS_DIR / "detected_figures.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {result_path}")


if __name__ == "__main__":
    main()
