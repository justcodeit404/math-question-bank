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
        "1000-基础·多元函数微分学-3": {
            "content": "设函数 $f(u)$ 可导，$z=yf(x^{y^2})$，则 $2x\\frac{\\partial z}{\\partial x}+y\\frac{\\partial z}{\\partial y}=$______."
        },
        "1000-基础·多元函数微分学-13": {
            "content": "设函数 $f(u,v)$ 具有二阶连续偏导数，函数 $g(x,y)=xy-f\\left(\\dfrac{y}{x}, \\dfrac{x}{y}\\right)$，求 $x^2\\dfrac{\\partial^2 g}{\\partial x^2}+2xy\\dfrac{\\partial^2 g}{\\partial x\\partial y}+y^2\\dfrac{\\partial^2 g}{\\partial y^2}$."
        },
        "1000-基础·多元函数微分学-15": {
            "content": "已知函数 $u(x,y)$ 满足 $2\\dfrac{\\partial^2 u}{\\partial x^2}-2\\dfrac{\\partial^2 u}{\\partial y^2}+3\\dfrac{\\partial u}{\\partial x}+3\\dfrac{\\partial u}{\\partial y}=0$，求 $a,b$ 的值使得在变换 $u(x,y)=v(x,y)e^{ax+by}$ 之下，上述等式可化为函数 $v(x,y)$ 的不含一阶偏导数的等式。"
        },
        "1000-基础·多元函数微分学-18": {
            "content": "设 $f(x,y)$ 在有界闭区域 $D$ 上连续，在 $D$ 内有一阶偏导数。若 $f(x,y)$ 在 $D$ 的边界 $\\partial D$ 上的值均为 $0$，且 $\\dfrac{\\partial[f(x,y)]}{\\partial x}+\\dfrac{\\partial[f(x,y)]}{\\partial y}=f(x,y)$，则 $f(x,y)$（    ）。"
        },
        "1000-基础·多元函数微分学-21": {
            "content": "求函数 $f(x,y)=x^3-3xy-y^2-y-9$ 的极值。"
        },
        "1000-基础·多元函数微分学-22": {
            "content": "求函数 $f(x,y)=x^2\\left(2x^2-4y-\\dfrac{1}{7}x^5\\right)+y^2$ 的极值。"
        },
        "1000-基础·二重积分-1": {
            "content": "设 $D$ 为由 $x=0$，$y=0$，$x+y=\\dfrac{1}{2}$，$x+y=1$ 所围成的区域，$I_1=\\iint\\limits_D \\ln^7(x+y)\\,d\\sigma$，$I_2=\\iint\\limits_D (x+y)^7\\,d\\sigma$，$I_3=\\iint\\limits_D \\sin^7(x+y)\\,d\\sigma$，则（    ）。"
        },
        "1000-基础·二重积分-3": {
            "content": "$\\lim\\limits_{r\\to 0}\\dfrac{1}{\\pi r^2}\\iint\\limits_{x^2+y^2\\leqslant r^2} e^{x^2-y^2}\\cos(x+y)dxdy=$（    ）。",
            "options": {"A": "$0$", "B": "$1$", "C": "$\\pi r^2$", "D": "$\\dfrac{1}{\\pi r^2}$"},
        },
        "1000-基础·二重积分-5": {
            "content": "$\\displaystyle\\int_0^1 dx\\int_0^{\\sqrt{x}} e^{\\frac{y^2}{2}} dy=$ ______。"
        },
        "1000-基础·二重积分-6": {
            "content": "$\\displaystyle\\int_0^1 dy\\int_0^{y^2} \\dfrac{x\\mathrm{e}^{x}}{1-\\sqrt{x}} dx=$ ______。"
        },
        "1000-基础·二重积分-7": {
            "content": "$I=\\displaystyle\\int_1^e dy\\int_0^{\\ln y} f(x,y)dx$（其中 $f(x,y)$ 连续）交换积分次序得（    ）。",
            "options": {
                "A": "$I=\\displaystyle\\int_0^{\\ln y} dx\\int_1^e f(x,y)dy$",
                "B": "$I=\\displaystyle\\int_0^1 dx\\int_{e^x}^e f(x,y)dy$",
                "C": "$I=\\displaystyle\\int_1^e dx\\int_0^{\\ln y} f(x,y)dy$",
                "D": "$I=\\displaystyle\\int_{e^x}^e dx\\int_0^1 f(x,y)dy$",
            },
        },
        "1000-基础·二重积分-8": {
            "content": "设 $f(x,y)$ 是连续函数，则 $\\displaystyle\\int_{\\frac{\\pi}{2}}^{\\frac{5\\pi}{6}} dx\\int_{\\sin x}^{1} f(x,y)dy=$（    ）。",
            "options": {
                "A": "$\\displaystyle\\int_{\\frac{1}{2}}^1 dy\\int_{\\frac{\\pi}{2}}^{\\arcsin y} f(x,y)dx$",
                "B": "$\\displaystyle\\int_{\\frac{1}{2}}^1 dy\\int_{\\pi-\\arcsin y}^{\\frac{5\\pi}{6}} f(x,y)dx$",
                "C": "$\\displaystyle\\int_0^{\\frac{1}{2}} dy\\int_{\\frac{\\pi}{2}}^{\\arcsin y} f(x,y)dx$",
                "D": "$\\displaystyle\\int_0^{\\frac{1}{2}} dy\\int_{\\pi-\\arcsin y}^{\\frac{\\pi}{2}} f(x,y)dx$",
            },
        },
        "1000-基础·二重积分-9": {
            "content": "设函数 $f(x,y)$ 连续，且 $f(x,y)=f(y,x)=f(-x,y)$，则 $\\displaystyle\\int_{-2}^2 dx\\int_{\\sqrt{4-x^2}}^{2} f(x,y)dy=$（    ）。",
            "options": {
                "A": "$\\displaystyle\\int_0^2\\left[\\int_{-2}^{-\\sqrt{4-y^2}} f(x,y)\\,dx+\\int_{\\sqrt{4-y^2}}^2 f(x,y)\\,dx\\right]dy$",
                "B": "$2\\displaystyle\\int_0^2\\left[\\int_{\\sqrt{4-y^2}}^2 f(x,y)\\,dy\\right]dx$",
                "C": "$4\\displaystyle\\int_0^{\\frac{\\pi}{4}} d\\theta\\int_2^{2\\sec\\theta} f(r\\cos\\theta,r\\sin\\theta)rdr$",
                "D": "$4\\displaystyle\\int_0^{\\arctan\\frac{1}{2}} d\\theta\\int_2^{2\\sec\\theta} f(r\\cos\\theta,r\\sin\\theta)rdr$",
            },
        },
        "1000-基础·二重积分-18": {
            "content": "计算 $I=\\displaystyle\\int_0^1 dy\\int_y^{\\sqrt{2y-y^2}} \\dfrac{1}{\\sqrt{x^2+y^2}\\sqrt{4-x^2-y^2}}dx$。"
        },
        "1000-基础·向量组-13": {
            "content": "设 $\\boldsymbol{\\alpha}_1=\\begin{pmatrix}1\\\\1\\\\0\\end{pmatrix}$，$\\boldsymbol{\\alpha}_2=\\begin{pmatrix}1\\\\0\\\\1\\end{pmatrix}$，$\\boldsymbol{\\alpha}_3=\\begin{pmatrix}-1\\\\0\\\\0\\end{pmatrix}$，记 $\\boldsymbol{\\beta}_1=\\boldsymbol{\\alpha}_1$，$\\boldsymbol{\\beta}_2=\\boldsymbol{\\alpha}_2-k_1\\boldsymbol{\\beta}_1$，$\\boldsymbol{\\beta}_3=\\boldsymbol{\\alpha}_3-k_2\\boldsymbol{\\beta}_1-k_3\\boldsymbol{\\beta}_2$，若 $\\boldsymbol{\\beta}_1$，$\\boldsymbol{\\beta}_2$，$\\boldsymbol{\\beta}_3$ 为正交向量组，则 $k_1$，$k_2$，$k_3$ 依次为（    ）。",
            "options": {
                "A": "$-\\dfrac{1}{2},\\ \\dfrac{1}{2},\\ -\\dfrac{1}{3}$",
                "B": "$-\\dfrac{1}{2},\\ \\dfrac{1}{2},\\ \\dfrac{1}{3}$",
                "C": "$\\dfrac{1}{2},\\ \\dfrac{1}{2},\\ \\dfrac{1}{3}$",
                "D": "$\\dfrac{1}{2},\\ -\\dfrac{1}{2},\\ -\\dfrac{1}{3}$",
            },
        },
        "1000-基础·向量组-14": {
            "content": "设向量组 $\\boldsymbol{\\alpha}_1=\\begin{pmatrix}1\\\\0\\\\-1\\end{pmatrix}$，$\\boldsymbol{\\alpha}_2=\\begin{pmatrix}a\\\\1\\\\1\\end{pmatrix}$，$\\boldsymbol{\\alpha}_3=\\begin{pmatrix}2\\\\1\\\\1\\end{pmatrix}$ 不可由向量组 $\\boldsymbol{\\beta}_1=\\begin{pmatrix}1\\\\1\\\\2\\end{pmatrix}$，$\\boldsymbol{\\beta}_2=\\begin{pmatrix}2\\\\3\\\\7\\end{pmatrix}$，$\\boldsymbol{\\beta}_3=\\begin{pmatrix}a\\\\0\\\\-a\\end{pmatrix}$ 线性表示，则 $a$ 的取值范围为______。"
        },
        "1000-基础·线性方程组-4": {
            "content": "设 $A$ 为 $n(n>2)$ 阶方阵，$r(A^*)=1$，$\\boldsymbol{\\alpha}_1$，$\\boldsymbol{\\alpha}_2$ 是非齐次线性方程组 $A\\boldsymbol{x}=\\boldsymbol{b}$ 的两个不同解，$k$ 为任意常数，则方程组 $A\\boldsymbol{x}=\\boldsymbol{b}$ 的通解为（    ）。"
        },
        "1000-基础·线性方程组-5": {
            "content": "设 $\\boldsymbol{\\alpha}_1=\\begin{pmatrix}4\\\\1\\\\2\\end{pmatrix}$，$\\boldsymbol{\\alpha}_2=\\begin{pmatrix}1\\\\1\\\\-1\\end{pmatrix}$，$\\boldsymbol{\\alpha}_3=\\begin{pmatrix}-2\\\\0\\\\4\\end{pmatrix}$，$\\boldsymbol{\\alpha}_4=\\begin{pmatrix}7\\\\2\\\\-3\\end{pmatrix}$，$A=[\\boldsymbol{\\alpha}_1,\\boldsymbol{\\alpha}_2,\\boldsymbol{\\alpha}_3,\\boldsymbol{\\alpha}_4]$，则 $A\\boldsymbol{x}=\\boldsymbol{\\alpha}_2+3\\boldsymbol{\\alpha}_4$ 的通解为______。"
        },
        "1000-基础·线性方程组-10": {
            "content": "已知线性方程组 $A\\boldsymbol{x}=k\\boldsymbol{\\beta}_1+\\boldsymbol{\\beta}_2$ 有解，其中 $A=\\begin{pmatrix}1&1&-1\\\\-1&-2&1\\\\1&-1&-1\\end{pmatrix}$，$\\boldsymbol{\\beta}_1=\\begin{pmatrix}2\\\\1\\\\3\\end{pmatrix}$，$\\boldsymbol{\\beta}_2=\\begin{pmatrix}1\\\\3\\\\-1\\end{pmatrix}$，则 $k$ 等于（    ）。"
        },
        "1000-基础·线性方程组-12": {
            "content": "设3维列向量组 $\\boldsymbol{\\alpha}_1$，$\\boldsymbol{\\alpha}_2$，$\\boldsymbol{\\alpha}_3$ 与 $\\boldsymbol{\\beta}_1$，$\\boldsymbol{\\beta}_2$，$\\boldsymbol{\\beta}_3$ 等价，记 $A=[\\boldsymbol{\\alpha}_1,\\boldsymbol{\\alpha}_2,\\boldsymbol{\\alpha}_3]$，$B=[\\boldsymbol{\\beta}_1,\\boldsymbol{\\beta}_2,\\boldsymbol{\\beta}_3]$，则下列结论：① $A\\boldsymbol{x}=\\boldsymbol{0}$ 与 $B\\boldsymbol{x}=\\boldsymbol{0}$ 同解；② $A^\\mathrm{T}\\boldsymbol{x}=\\boldsymbol{0}$ 与 $B^\\mathrm{T}\\boldsymbol{x}=\\boldsymbol{0}$ 同解；③ $\\begin{pmatrix}A\\\\B\\end{pmatrix}\\boldsymbol{x}=\\boldsymbol{0}$ 与 $A\\boldsymbol{x}=\\boldsymbol{0}$ 同解；④ $\\begin{pmatrix}A^\\mathrm{T}\\\\B^\\mathrm{T}\\end{pmatrix}\\boldsymbol{x}=\\boldsymbol{0}$ 与 $A^\\mathrm{T}\\boldsymbol{x}=\\boldsymbol{0}$ 同解。所有正确结论的序号是（    ）。",
            "options": {"A": "①②", "B": "①③", "C": "②④", "D": "①②③④"},
        },
        "1000-基础·线性方程组-13": {
            "content": "设 $A$ 为 $m\\times n$ 矩阵，$\\boldsymbol{e}=[1,1,\\cdots,1]^\\mathrm{T}$。若方程组 $A\\boldsymbol{y}=\\boldsymbol{e}$ 有解，则对于 (I) $A^\\mathrm{T}\\boldsymbol{x}=\\boldsymbol{0}$ 与 (II) $\\begin{cases}A^\\mathrm{T}\\boldsymbol{x}=\\boldsymbol{0},\\\\\\boldsymbol{e}^\\mathrm{T}\\boldsymbol{x}=0,\\end{cases}$ 说法正确的是（    ）。"
        },
        "1000-基础·特征值与特征向量-6": {
            "content": "设 $A$ 是3阶矩阵，将 $A$ 的第2列加到第3列得矩阵 $B$，再将 $B$ 的第3行的 $-1$ 倍加到第2行得 $\\begin{pmatrix}1&1&0\\\\0&2&0\\\\0&2&a\\end{pmatrix}$，其中 $a$ 为常数，则 $A$ 的特征值为（    ）。"
        },
        "1000-基础·特征值与特征向量-7": {
            "options": {
                "A": "$\\begin{pmatrix}1&2&-1\\\\2&0&1\\\\-1&1&0\\end{pmatrix}$",
                "B": "$\\begin{pmatrix}3&2&1\\\\0&2&1\\\\0&0&0\\end{pmatrix}$",
                "C": "$\\begin{pmatrix}2&0&0\\\\0&2&0\\\\1&0&1\\end{pmatrix}$",
                "D": "$\\begin{pmatrix}0&0&0\\\\1&2&0\\\\0&1&2\\end{pmatrix}$",
            }
        },
        "1000-基础·特征值与特征向量-8": {
            "content": "设 $A$ 为2阶矩阵，$\\boldsymbol{\\alpha}=\\begin{pmatrix}1\\\\0\\end{pmatrix}$ 是方程组 $A\\boldsymbol{x}=\\boldsymbol{0}$ 的解，$\\boldsymbol{\\beta}=\\begin{pmatrix}1\\\\1\\end{pmatrix}$ 是方程组 $A\\boldsymbol{x}=\\boldsymbol{\\beta}$ 的解，则矩阵 $A=$______。"
        },
        "1000-基础·特征值与特征向量-9": {
            "content": "已知 $A$ 为2阶方阵，可逆矩阵 $P=[\\boldsymbol{\\alpha},\\boldsymbol{\\beta}]$ 使得 $P^{-1}AP=\\begin{pmatrix}1&0\\\\0&2\\end{pmatrix}$，$Q=[\\boldsymbol{\\beta},\\boldsymbol{\\alpha}]$，则 $Q^{-1}A^*Q=$______。"
        },
        "1000-基础·特征值与特征向量-10": {
            "content": "设 $1$ 与 $-1$ 是矩阵 $A=\\begin{pmatrix}3&1&-2\\\\-a&-1&a\\\\4&1&-3\\end{pmatrix}$ 的特征值，若矩阵 $A$ 可相似对角化，则 $a=$（    ）。"
        },
        "1000-基础·特征值与特征向量-13": {
            "content": "设 $A$ 是3阶实对称矩阵，满足 $A+A^2+\\dfrac{1}{2}A^3=\\boldsymbol{0}$，则 $r(A)=$______。"
        },
        "1000-基础·二次型-2": {
            "options": {"A": "$a=-1$", "B": "$a=1$", "C": "$a\\geqslant 0$", "D": "$a<0$"}
        },
        "1000-基础·二次型-4": {
            "options": {"A": "$0$", "B": "$1$", "C": "$2$", "D": "$3$"}
        },
        "1000-基础·二次型-5": {
            "options": {
                "A": "$2y_1^2-y_2^2+y_3^2$",
                "B": "$2y_1^2+y_2^2-y_3^2$",
                "C": "$-2y_1^2+y_2^2+y_3^2$",
                "D": "$-2y_1^2-y_2^2+y_3^2$",
            }
        },
        "1000-基础·二次型-7": {
            "sub_questions": [
                "(1) 求 $a$ 的值和正交矩阵 $Q$。",
                "(2) 设矩阵 $B=\\begin{pmatrix}1&0&0\\\\c&b&0\\\\-1&-1&1\\end{pmatrix}$，若 $A$ 与 $B$ 相似，求 $b$，$c$ 的值。在此情形下，是否存在正交矩阵 $P$，使 $P^{\\mathrm{T}}AP=B$？若存在，求 $P$；若不存在，请说明理由。",
            ]
        },
        "1000-基础·二次型-8": {
            "content": "设 $A=\\begin{pmatrix}0&0&0&1\\\\0&0&1&0\\\\0&1&0&0\\\\1&0&0&0\\end{pmatrix}$，$B=\\begin{pmatrix}-1&0&0&0\\\\0&-1&0&0\\\\0&0&1&0\\\\0&0&0&1\\end{pmatrix}$，则 $A$ 和 $B$（    ）。"
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
