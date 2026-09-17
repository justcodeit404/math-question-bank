#!/usr/bin/env python3
"""应用已逐页对照原书确认的隔离题修复，并补生成缺失题图。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent.parent

REPAIRS = {
    "660题": {
        "660-260": {
            "options": {
                "A": "$\\frac{\\varepsilon \\sin y}{(1-\\varepsilon \\cos y)^3}$",
                "B": "$\\frac{-\\varepsilon \\sin y}{(1-\\varepsilon \\cos y)^2}$",
                "C": "$\\frac{-\\varepsilon \\sin y}{(1-\\varepsilon \\cos y)^3}$",
                "D": "$\\frac{\\varepsilon \\sin y}{(1-\\varepsilon \\cos y)^2}$",
            }
        },
        "660-429": {
            "options": {
                "A": "$-4\\mathrm{d}x+\\mathrm{d}y$",
                "B": "$-4\\mathrm{d}x+2\\mathrm{d}y$",
                "C": "$-2\\mathrm{d}x+2\\mathrm{d}y$",
                "D": "$-2\\mathrm{d}x+\\mathrm{d}y$",
            }
        },
    },
    "880题": {
        "880-50": {
            "content": "设 $0<a_1<a_2$，则 $\\lim\\limits_{n\\to\\infty}(a_1^{-n}+a_2^{-n})^{\\frac{1}{n}}=\\underline{\\qquad}$。"
        },
        "880-56": {
            "content": "设 $f''(1)$ 存在，$f'(1)\\neq0$，则 $\\lim\\limits_{x\\to1}\\left[\\frac{1}{f'(1)(x-1)}-\\frac{1}{f(x)-f(1)}\\right]=\\underline{\\qquad}$。"
        },
        "880-288": {
            "content": "设 $I_1=\\int_0^{\\frac{\\pi}{2}}\\sin(\\sin x)\\,\\mathrm{d}x$，$I_2=\\int_0^{\\frac{\\pi}{2}}\\cos(\\sin x)\\,\\mathrm{d}x$，则（　）。",
            "options": {"A": "$I_1<1<I_2$", "B": "$I_2<1<I_1$", "C": "$1<I_1<I_2$", "D": "$I_1<I_2<1$"},
        },
        "880-289": {
            "content": "设 $I_1=\\int_0^1\\ln(1+x)\\,\\mathrm{d}x$，$I_2=\\int_0^1\\frac{\\arctan x}{1+x}\\,\\mathrm{d}x$，$I_3=\\int_0^1\\sqrt{\\ln(1+x)}\\,\\mathrm{d}x$，则（　）。",
            "options": {"A": "$I_3>I_1>I_2$", "B": "$I_3>I_2>I_1$", "C": "$I_1>I_2>I_3$", "D": "$I_2>I_3>I_1$"},
        },
        "880-290": {
            "content": "设 $I_1=\\int_0^{\\frac{\\pi}{2}}\\frac{\\cos x}{1+x^2}\\,\\mathrm{d}x$，$I_2=\\int_0^{\\frac{\\pi}{2}}\\frac{\\sin x}{1+x^2}\\,\\mathrm{d}x$，$I_3=\\int_0^{\\frac{\\pi}{2}}\\frac{\\sin x}{(1+x)^2}\\,\\mathrm{d}x$，则（　）。",
            "options": {"A": "$I_2>I_1>I_3$", "B": "$I_3>I_2>I_1$", "C": "$I_1>I_2>I_3$", "D": "$I_2>I_3>I_1$"},
        },
        "880-297": {
            "content": "设螺线 $r=\\theta\\,(0\\leq\\theta\\leq2\\pi)$ 与极轴所围区域的面积为 $A$，则 $A=$（　）。",
            "options": {
                "A": "$\\lim\\limits_{n\\to\\infty}\\sum_{i=1}^{n}\\frac{4\\pi^3i^2}{n^3}$",
                "B": "$\\lim\\limits_{n\\to\\infty}\\sum_{i=1}^{n}\\frac{4\\pi^3i^2}{n^2}$",
                "C": "$\\lim\\limits_{n\\to\\infty}\\sum_{i=1}^{n}\\frac{8\\pi^3i^2}{n^3}$",
                "D": "$\\lim\\limits_{n\\to\\infty}\\sum_{i=1}^{n}\\frac{2\\pi^3i^2}{n^2}$",
            },
        },
        "880-392": {
            "content": "设 $f(x,y)=\\begin{cases}\\dfrac{2x|y|}{\\sqrt{x^2+y^2}},&x^2+y^2\\neq0,\\\\0,&x^2+y^2=0.\\end{cases}$ 若 $z=f(\\tan t,\\ln(1+t))$，则 $\\left.\\dfrac{\\mathrm{d}z}{\\mathrm{d}t}\\right|_{t=0}=$（　）。",
            "options": {"A": "$0$", "B": "$1$", "C": "$2$", "D": "$\\sqrt{2}$"},
        },
        "880-466": {
            "content": "积分 $I=\\int_0^2\\mathrm{d}x\\int_0^{\\frac{x^2}{2}}f(x,y)\\,\\mathrm{d}y+\\int_2^{2\\sqrt2}\\mathrm{d}x\\int_0^{\\sqrt{8-x^2}}f(x,y)\\,\\mathrm{d}y=$（　）。",
            "options": {
                "A": "$\\int_0^{\\sqrt2}\\mathrm{d}y\\int_{\\sqrt y}^{\\sqrt{8-y^2}}f(x,y)\\,\\mathrm{d}x$",
                "B": "$\\int_0^{\\sqrt2}\\mathrm{d}y\\int_{\\sqrt{2y}}^{\\sqrt{8-y^2}}f(x,y)\\,\\mathrm{d}x$",
                "C": "$\\int_0^2\\mathrm{d}y\\int_{\\sqrt{2y}}^{\\sqrt{8-y^2}}f(x,y)\\,\\mathrm{d}x$",
                "D": "$\\int_0^2\\mathrm{d}y\\int_{\\sqrt y}^{\\sqrt{8-y^2}}f(x,y)\\,\\mathrm{d}x$",
            },
        },
        "880-798": {
            "content": "设 $A=\\begin{pmatrix}2&0&0&2\\\\1&1&0&3\\\\0&1&3&5\\end{pmatrix}$，$B=\\begin{pmatrix}1&0&1&2\\\\0&2&0&4\\\\0&-1&a-1&a-3\\end{pmatrix}$，$\\boldsymbol{\\alpha}=\\begin{pmatrix}2\\\\2\\\\1\\end{pmatrix}$，$\\boldsymbol{\\beta}=\\begin{pmatrix}1\\\\2\\\\-1\\end{pmatrix}$。",
            "sub_questions": [
                "(I) 证明：方程组 $AX=\\boldsymbol{\\alpha}$ 的解均是方程组 $BX=\\boldsymbol{\\beta}$ 的解；",
                "(II) 若方程组 $AX=\\boldsymbol{\\alpha}$ 与方程组 $BX=\\boldsymbol{\\beta}$ 不同解，求 $a$ 的值。",
            ],
        },
        "880-825": {
            "content": "设 $A$ 为 $n$ 阶矩阵，且 $A^2=A$，$r(A)=r$（$r<n$），计算 $|3E-A|$。",
            "sub_questions": [
                "(I) $A$ 是 $n$ 阶实对称矩阵；",
                "(II) $A$ 是一般 $n$ 阶矩阵。",
            ],
        },
    },
    "1000题": {
        "1000-综合·测试卷二-2": {"options": {"A": "0", "B": "1", "C": "2", "D": "3"}},
        "1000-基础·多元函数微分学-15": {
            "content": "已知函数 $u(x,y)$ 满足 $2\\dfrac{\\partial^2 u}{\\partial x^2}-2\\dfrac{\\partial^2 u}{\\partial y^2}+3\\dfrac{\\partial u}{\\partial x}+3\\dfrac{\\partial u}{\\partial y}=0$，求 $a,b$ 的值使得在变换 $u(x,y)=v(x,y)e^{ax+by}$ 之下，上述等式可化为函数 $v(x,y)$ 的不含一阶偏导数的等式。"
        },
    },
    "大学深埋": {
        "大学深埋-线代 · 行列式和矩阵-例41-p41": {
            "options": {"A": "$r(A)=n$", "B": "$r(B)=n$", "C": "$r(A)+r(B)<n$", "D": "$r(A)+r(B)=n$"}
        }
    },
}

# (页码, 文件名, 裁剪矩形 x0,y0,x1,y1)；矩形在 create_missing_crops 内转 fitz.Rect，避免顶层依赖 fitz
CROPS = {
    33: ("一元函数微分学_例23_p33.png", (40, 340, 560, 505)),
    34: ("一元函数微分学_例24_p34.png", (40, 35, 560, 175)),
    35: ("方程根与零点问题_例1_p35.png", (40, 110, 560, 235)),
    57: ("凹凸性_例1_p57.png", (40, 110, 560, 265)),
    121: ("微积分应用_例7_p121.png", (40, 260, 560, 365)),
    122: ("微积分应用_例10_p122.png", (40, 267, 560, 370)),
}


def apply_repairs(book: str | None = None, uid: str | None = None) -> None:
    for book_name, repairs in REPAIRS.items():
        if book is not None and book_name != book:
            continue
        if uid is not None:
            if uid not in repairs:
                raise RuntimeError(f"{book_name} 的修复清单中没有 UID: {uid}")
            repairs = {uid: repairs[uid]}
        path = ROOT / book_name / "questions.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        by_uid = {
            str(question.get("uid") or ""): question
            for chapter in data.get("chapters", [])
            for question in chapter.get("questions", [])
        }
        missing = sorted(set(repairs) - set(by_uid))
        if missing:
            raise RuntimeError(f"{book_name} 找不到 UID: {missing}")
        for qid, fields in repairs.items():
            by_uid[qid].update(fields)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        print(f"已修复 {book_name}: {len(repairs)} 题")


def create_missing_crops() -> None:
    import fitz  # 懒加载：只在裁图时需要（系统 Python 通常没装）

    source = REPO_ROOT / "资料" / "数学2" / "电子资料" / "01 27大雪深埋做题本（高数）.pdf"
    output = ROOT / "大学深埋" / "cropped_images"
    output.mkdir(parents=True, exist_ok=True)
    document = fitz.open(source)
    try:
        for page_no, (filename, clip) in CROPS.items():
            pixmap = document[page_no - 1].get_pixmap(dpi=200, clip=fitz.Rect(*clip), alpha=False)
            pixmap.save(output / filename)
            print(f"已裁图: {filename}")
    finally:
        document.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="隔离题修复 / 补裁题图（互不相干，分开跑）")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("repairs", help="应用 REPAIRS 修复清单（默认）")
    sub.add_parser("crops", help="补生成大学深埋缺失题图（依赖本机 PDF + fitz）")
    args = parser.parse_args()
    if args.command in (None, "repairs"):
        apply_repairs()
    if args.command == "crops":
        create_missing_crops()
