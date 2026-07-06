#!/usr/bin/env python3
"""
批量修复已知的数据质量问题。

用法：
  python scripts/fix_quality_issues.py --run
  python scripts/fix_quality_issues.py --dry-run
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

ROOT = Path(__file__).resolve().parent.parent


def backup(path: Path):
    bak = path.with_suffix(path.suffix + '.bak.quality_fix')
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _fix_blank_suffix(text: str) -> str:
    r"""
    修复填空题结尾下划线空格的 $ 不闭合问题。

    只处理末尾是 ``\_...\_$。`` 的情况：
      - 若全文 $ 数量为奇数，说明末尾的 $ 是 stray，需要让下划线区域进入数学模式。
      - 下划线前已经是 $ 时，删除这个 stray opener（例：``$S=$\_\_\_$。`` → ``$S=\_\_\_$。``）。
      - 下划线前不是 $ 时，在下划线前补 $（例：``为\_\_\_\_$。`` → ``为$\_\_\_\_$。``）。
    """
    if not text.endswith('。'):
        return text
    # 最后倒数第二个字符必须是 $，且前面是反斜杠+下划线序列
    if text[-2] != '$':
        return text
    # 从下划线末尾向前扫描连续的 \_ 对
    q = len(text) - 2  # 指向末尾 $ 的位置
    while q >= 2 and text[q - 2:q] == r'\_':
        q -= 2
    # 没有下划线则无需处理
    if q == len(text) - 2:
        return text
    # 若 $ 总数已经是偶数，说明末尾 $ 是正常闭合符，不动
    if text.count('$') % 2 == 0:
        return text
    if q > 0 and text[q - 1] == '$':
        # stray opener：删掉它，让下划线并入前面已有的 math
        return text[:q - 1] + text[q:len(text) - 2] + '$。'
    # 缺少 opening $，补一个
    return text[:q] + '$' + text[q:len(text) - 2] + '$。'


def save(path: Path, data):
    write_json_atomic(path, data, indent=2)


def walk_questions(data):
    """遍历所有题目，返回可修改的字典引用。"""
    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            yield q


def fix_660(data, dry_run: bool) -> int:
    count = 0
    for q in walk_questions(data):
        uid = q.get('uid')
        if uid == '660-416':
            old = q.get('content', '')
            new = "设隐函数 $z = z(x,y)$ 由方程 $y + xz = x f(y^2 - z^2)$ 确定，$f$ 可微，则 $x \\frac{\\partial z}{\\partial x} + z \\frac{\\partial z}{\\partial y}$ 等于"
            if old != new:
                q['content'] = new
                count += 1
        if uid in ('660-419', '660-598'):
            opts = q.get('options') or {}
            for k, v in opts.items():
                new_v = v.replace('⇒', '\\Rightarrow').replace('⇔', '\\Leftrightarrow')
                # 选项里的罗马数字和箭头最好整体放在数学模式
                # 例如 "②⇒③⇒①." -> "$②\\Rightarrow③\\Rightarrow①$."
                new_v2 = re.sub(r'^([①②③④ⅠⅡⅢⅣ]+)([⇒⇔]+)([①②③④ⅠⅡⅢⅣ]+)\\.$', r'$\1\2\3$.', new_v)
                if new_v2 == new_v:
                    new_v2 = re.sub(r'^([①②③④ⅠⅡⅢⅣ]+)([⇒⇔]+)([①②③④ⅠⅡⅢⅣ]+)$', r'$\1\2\3$', new_v)
                new_v2 = new_v2.replace('\\Rightarrow', '\\Rightarrow').replace('\\Leftrightarrow', '\\Leftrightarrow')
                # 再次确认箭头替换（因为前面的 regex 里 \2 仍是 Unicode，需要转成命令）
                new_v2 = new_v2.replace('⇒', '\\Rightarrow').replace('⇔', '\\Leftrightarrow')
                if new_v2 != v:
                    opts[k] = new_v2
                    count += 1
    return count


def fix_1000(data, dry_run: bool) -> int:
    count = 0
    for q in walk_questions(data):
        uid = q.get('uid')

        # 1. 综合·测试卷二-1 的 options 是 int，转成字符串
        if uid == '1000-综合·测试卷二-1':
            opts = q.get('options')
            if isinstance(opts, dict):
                for k, v in list(opts.items()):
                    if not isinstance(v, str):
                        opts[k] = str(v)
                        count += 1

        # 1b. 提取时漏掉的填空下划线
        if uid == '1000-强化·一元函数微分学的计算-2':
            old = q.get('content', '')
            new = old.replace('求 $f\'\'(0)$。', '求 $f\'\'(0)=$\\_\\_\\_\\_\\_\\_\\_\\_$。')
            if new != old:
                q['content'] = new
                count += 1

        # 2. 填空题 unbalanced_dollars: ...\_\_\_\_\_\_$。 -> ...$\_\_\_\_\_\_$。
        if q.get('type') == '填空题':
            old = q.get('content', '')
            new = _fix_blank_suffix(old)
            if new != old:
                q['content'] = new
                count += 1

        # 3. 中文标点 inside/outside math
        old = q.get('content', '')
        new = old
        # 证明题 $$...x。$$ -> $$...x$$。
        new = re.sub(r'(\\\[|\\begin\{[^}]+\}|\$\$)([^$]+?)。(\]|\\end\{[^}]+\}|\$\$)', r'\1\2\3。', new)
        new = re.sub(r'\$\$([^$]+?)。\$\$', r'$$$$\1$$$$。', new)
        # 选择题结尾 =（ ）$。 -> =(\quad)$。
        new = re.sub(r'=（\s*）\$。', r'=(\\quad)$。', new)
        if new != old:
            q['content'] = new
            count += 1
    return count


# ---------- 大学深埋：逐题手工修复 ----------
大学深埋_FIXES = {
    '大学深埋-函数极限-例1-p3': (
        '已知$\\lim\\limits_{x\\to+\\infty}f(x)$存在，且$f(x)=\\dfrac{x^{1+x}}{(1+x)^{x}}-\\dfrac{x}{\\mathrm{e}}+2\\cdot\\lim\\limits_{x\\to+\\infty}f(x)$，求$f(x)$。'
    ),
    '大学深埋-函数极限-例2-p3': (
        '已知$\\varphi(x)$是$x\\to0$时的无穷小量，则下列说法中正确的有几项（    ）\\n'
        '①$\\lim\\limits_{x\\to0}\\dfrac{\\sin\\varphi(x)}{\\varphi(x)}=1$；\\n'
        '②当$x\\to0$时，$\\sin\\varphi(x)$与$\\varphi(x)$是等价的无穷小量；\\n'
        '③当$x\\to0$时，$\\dfrac{1}{\\varphi(x)}$是无穷大量；\\n'
        '④已知连续函数$f(x)$满足$\\lim\\limits_{x\\to0}f(x)=1$，则$\\lim\\limits_{x\\to0}f(\\varphi(x))=1$；'
    ),
    '大学深埋-函数极限-例3-p4': (
        '当$x\\to0$时，$\\alpha(x),\\beta(x)$是非零无穷小量，则以下的命题中，\\n'
        '①$\\alpha(x)\\sim\\beta(x)$，则$\\alpha^{2}(x)\\sim\\beta^{2}(x)$；\\n'
        '②$\\alpha^{2}(x)\\sim\\beta^{2}(x)$，则$\\alpha(x)\\sim\\beta(x)$；\\n'
        '③$\\alpha(x)\\sim\\beta(x)$，则$\\alpha(x)-\\beta(x)=o(\\alpha(x))$；\\n'
        '④$\\alpha(x)-\\beta(x)=o(\\alpha(x))$，则$\\alpha(x)\\sim\\beta(x)$.\\n'
        '所有真命题的序号是（    ）'
    ),
    '大学深埋-函数极限-例7-p6': (
        '设函数$y=f(x)$由参数方程$\\begin{cases}x=\\dfrac{1}{t-2}\\\\y=\\dfrac{t\\ln|t|}{|t-2|}\\end{cases}$确定，则$f(x)$的第一类间断点的个数为（    ）'
    ),
    '大学深埋-函数极限-例8-p6': (
        '设$f(x)$在$(0,+\\infty)$内有定义，有一个间断点，而$g(x)=\\lim\\limits_{n\\to\\infty}\\dfrac{\\ln(\\mathrm{e}^{n}+x^{n})}{n}(x>0)$，则（    ）'
    ),
    '大学深埋-函数极限-例9-p7': (
        '设函数$f(x)$在$(0,\\pi)$内可导，$f(x)>0$，$f\\left(\\dfrac{\\pi}{2}\\right)=\\dfrac{4}{\\pi^{2}}$，且$\\lim\\limits_{h\\to0}\\left[\\dfrac{f(x+h\\sin x)}{f(x)}\\right]^{\\dfrac{1}{h}}=\\mathrm{e}^{\\dfrac{2(\\cos x-\\sin x)}{x}}$，$x\\in(0,+\\infty)$.'
    ),
    '大学深埋-函数极限-例10-p7': (
        '设函数$f(x)$在区间$[1,+\\infty)$上连续可导，且$f\'(x)=\\dfrac{1}{1+f^{2}(x)}\\left[\\sqrt{\\dfrac{1}{x}}-\\sqrt{\\ln\\left(1+\\dfrac{1}{x}\\right)}\\right]$，证明：$\\lim\\limits_{x\\to+\\infty}f(x)$存在.'
    ),
}


def fix_大学深埋(data, dry_run: bool) -> int:
    count = 0
    for q in walk_questions(data):
        uid = q.get('uid')
        if uid in 大学深埋_FIXES:
            old = q.get('content', '')
            new = 大学深埋_FIXES[uid]
            if old != new:
                q['content'] = new
                count += 1

        # sub_questions 也可能有同样问题
        subs = q.get('sub_questions') or []
        if uid == '大学深埋-函数极限-例9-p7' and subs:
            new_subs = [
                '(1)求$f(x)$；',
                '(2)求证：$f(x)$在$(0,\\pi)$上有界.'
            ]
            if subs != new_subs:
                subs[:] = new_subs
                count += 1
        if uid == '大学深埋-函数极限-例10-p7' and subs:
            new_subs = [
                '(1)证明：当$x\\geq1$时，$\\dfrac{1}{1+x}<\\ln\\left(1+\\dfrac{1}{x}\\right)<\\dfrac{1}{x}$；',
                '(2)设函数$f(x)$在区间$[1,+\\infty)$上连续可导，且$f\'(x)=\\dfrac{1}{1+f^{2}(x)}\\left[\\sqrt{\\dfrac{1}{x}}-\\sqrt{\\ln\\left(1+\\dfrac{1}{x}\\right)}\\right]$，证明：$\\lim\\limits_{x\\to+\\infty}f(x)$存在.'
            ]
            if subs != new_subs:
                subs[:] = new_subs
                count += 1
    return count


def run(book_dir: Path, fix_fn, dry_run: bool):
    path = book_dir / 'questions.json'
    if not path.exists():
        for alt in book_dir.glob('*.json'):
            if '题目' in alt.name or 'questions' in alt.name.lower():
                path = alt
                break
    if not path.exists():
        print(f'[跳过] 找不到 {book_dir} 的题目 JSON')
        return

    data = load(path)
    count = fix_fn(data, dry_run)
    print(f'[{book_dir.name}] 修复 {count} 处')
    if count and not dry_run:
        bak = backup(path)
        save(path, data)
        print(f'  已备份: {bak}')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true', help='只打印不写入')
    args = p.parse_args()

    run(ROOT / '660题', fix_660, args.dry_run)
    run(ROOT / '1000题', fix_1000, args.dry_run)
    run(ROOT / '大学深埋', fix_大学深埋, args.dry_run)


if __name__ == '__main__':
    main()
