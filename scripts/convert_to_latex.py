r"""880题数学公式转换主脚本。

单遍完成所有转换：Unicode→LaTeX、函数名、\lim、分式、求值记号、Sigma 等。
从 questions.json.bak 读取原始数据，输出到 questions.json。

用法：python scripts/convert_to_latex.py [--no-frac]
  --no-frac  跳过分式转换（供 convert_fractions.py 分步调用）
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

QUESTIONS_DIR = Path(__file__).resolve().parent.parent / '880题'
QUESTIONS_JSON = QUESTIONS_DIR / 'questions.json'
BACKUP_JSON = QUESTIONS_DIR / 'questions.json.bak'

BS = chr(92)  # backslash, 避免 shell 吞掉

# ── Unicode → LaTeX 映射表 ──────────────────────────────────────────────

SUPERSCRIPT_MAP = {
    '⁰': '^{0}', '¹': '^{1}', '²': '^{2}', '³': '^{3}',
    '⁴': '^{4}', '⁵': '^{5}', '⁶': '^{6}', '⁷': '^{7}',
    '⁸': '^{8}', '⁹': '^{9}', '⁺': '^{+}', '⁻': '^{-}',
    '⁽': '^{(', '⁾': ')}',
    'ᵃ': '^{a}', 'ᵇ': '^{b}', 'ᶜ': '^{c}', 'ᵈ': '^{d}',
    'ᵉ': '^{e}', 'ᶠ': '^{f}', 'ᵍ': '^{g}', 'ʰ': '^{h}',
    'ⁱ': '^{i}', 'ʲ': '^{j}', 'ᵏ': '^{k}', 'ˡ': '^{l}',
    'ᵐ': '^{m}', 'ⁿ': '^{n}', 'ᵒ': '^{o}', 'ᵖ': '^{p}',
    'ʳ': '^{r}', 'ˢ': '^{s}', 'ᵗ': '^{t}', 'ᵘ': '^{u}',
    'ᵛ': '^{v}', 'ʷ': '^{w}', 'ˣ': '^{x}', 'ʸ': '^{y}',
    'ᶻ': '^{z}',
    # Phonetic Extensions (U+1D00-U+1D7F)
    'ᴾ': '^{P}', 'ᵖ': '^{p}',
    'ᶿ': '^{'+BS+'theta}',
    'ᵝ': '^{'+BS+'beta}',
    'ᵞ': '^{'+BS+'gamma}',
}

SUBSCRIPT_MAP = {
    '₀': '_{0}', '₁': '_{1}', '₂': '_{2}', '₃': '_{3}',
    '₄': '_{4}', '₅': '_{5}', '₆': '_{6}', '₇': '_{7}',
    '₈': '_{8}', '₉': '_{9}',
    'ₙ': '_{n}', 'ₖ': '_{k}',
    '₍': '_{(', '₎': ")",
    '₊': '_{+}', '₋': '_{-}', '₌': '_{=}',
    # Unicode subscript letters
    'ₐ': '_{a}', 'ₑ': '_{e}', 'ₒ': '_{o}', 'ₓ': '_{x}',
    'ₕ': '_{h}', 'ₗ': '_{l}', 'ₘ': '_{m}',
    'ₚ': '_{p}', 'ₛ': '_{s}', 'ₜ': '_{t}',
    # Phonetic Extensions (U+1D60-U+1D7F)
    'ᵢ': '_{i}', 'ᵣ': '_{r}', 'ᵤ': '_{u}', 'ᵥ': '_{v}',
    'ᵦ': '_{'+BS+'beta}', 'ᵧ': '_{'+BS+'gamma}',
    'ᵨ': '_{'+BS+'rho}', 'ᵩ': '_{'+BS+'phi}', 'ᵪ': '_{'+BS+'chi}',
}

# Unicode 下标字母 → ASCII（用于求值记号等上下文）
SUBSCRIPT_LETTER_MAP = {
    'ₐ': 'a', 'ₑ': 'e', 'ₒ': 'o', 'ₓ': 'x',
    'ₕ': 'h', 'ₗ': 'l', 'ₘ': 'm', 'ₙ': 'n',
    'ₚ': 'p', 'ₛ': 's', 'ₜ': 't', 'ᵧ': 'y',
    'ᵢ': 'i', 'ⱼ': 'j',
    # Phonetic Extensions subscripts
    'ᵦ': BS + 'beta', 'ᵧ': BS + 'gamma',
}

# Unicode 分数字符 → ASCII
FRACTION_CHAR_MAP = {
    '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅓': '1/3', '⅔': '2/3',
}

MATH_SYMBOL_MAP = {
    '∈': r'\in', '∞': r'\infty', '∀': r'\forall', '∃': r'\exists',
    '≤': r'\leq', '≥': r'\geq', '≠': r'\neq', '≈': r'\approx',
    '≡': r'\equiv', '±': r'\pm', '∓': r'\mp', '×': r'\times',
    '÷': r'\div', '√': r'\sqrt', '∑': r'\sum', '∏': r'\prod',
    '∫': r'\int', '∬': r'\iint', '∮': r'\oint',
    '∂': r'\partial', '∇': r'\nabla', '∆': r'\Delta',
    'α': r'\alpha', 'β': r'\beta', 'γ': r'\gamma', 'δ': r'\delta',
    'ε': r'\varepsilon', 'ζ': r'\zeta', 'η': r'\eta', 'θ': r'\theta',
    'λ': r'\lambda', 'μ': r'\mu', 'ξ': r'\xi', 'π': r'\pi',
    'ρ': r'\rho', 'σ': r'\sigma', 'τ': r'\tau', 'φ': r'\varphi',
    'χ': r'\chi', 'ψ': r'\psi', 'ω': r'\omega',
    'Γ': r'\Gamma', 'Δ': r'\Delta', 'Θ': r'\Theta', 'Λ': r'\Lambda',
    'Σ': r'\Sigma', 'Φ': r'\Phi', 'Ψ': r'\Psi', 'Ω': r'\Omega',
    '·': r'\cdot ', '…': r'\cdots', '→': r'\to', '←': r'\leftarrow',
    '⇒': r'\Rightarrow', '′': "'", '″': "''", '‴': "'''",
    '⌊': r'\lfloor', '⌋': r'\rfloor', '⌈': r'\lceil', '⌉': r'\rceil',
    '‖': r'\|',
}

FUNCTION_NAMES = [
    'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
    'arcsin', 'arccos', 'arctan',
    'sinh', 'cosh', 'tanh', 'coth',
    'ln', 'log', 'exp', 'lim', 'max', 'min', 'sup', 'inf',
    'det', 'dim', 'ker', 'gcd',
]

# 预编译正则
_FUNC_PATTERN = re.compile(
    r'(?<![a-zA-Z' + BS * 2 + r'])(' + '|'.join(FUNCTION_NAMES) + r')(?=[a-zA-Z(])'
)
_FUNC_REPL = lambda m: BS + m.group(1) + ' '
_INTEGRAL_RE = re.compile(r'\\int(?![a-z])([a-z])(\w*)\^', re.IGNORECASE)
_PIECEWISE_RE = re.compile(r'(?<!\^)\{((?:[^{}]*\{[^{}]*\}[^{}]*)*[^{}]*);((?:[^{}]*\{[^{}]*\}[^{}]*)*[^{}]*)\}')
_CONSEC_SUP_RE = re.compile(r'\^\{([^}]*)\}\^\{([^}]*)\}')
_SUBSCRIPT_LETTER_RE = re.compile(r'_([₀-₉ₐ-ₜᵧᵢⱼ])(?=[^{}])')


# ── 第一阶段：Unicode → LaTeX ────────────────────────────────────────────

def unicode_to_latex(s):
    """将 Unicode 数学符号转换为 LaTeX 命令。"""
    # 上标/下标
    for u, l in {**SUPERSCRIPT_MAP, **SUBSCRIPT_MAP}.items():
        s = s.replace(u, l)
    # Unicode 下标字母 → ASCII
    for u, a in SUBSCRIPT_LETTER_MAP.items():
        s = s.replace(u, a)
    # Unicode 分数字符 → ASCII
    for u, a in FRACTION_CHAR_MAP.items():
        s = s.replace(u, a)
    # 数学符号
    for u, l in MATH_SYMBOL_MAP.items():
        s = s.replace(u, l)
    # 合并连续上标
    # 先处理字母+数字上标: ^{x}^{2} → ^{x^{2}}（嵌套，变量的指数）
    _VAR_EXP_RE = re.compile(r'\^\{([a-zA-Z]+)\}\^\{(\d+)\}')
    while _VAR_EXP_RE.search(s):
        s = _VAR_EXP_RE.sub(r'^{\1^{\2}}', s)
    # 其余连续上标拼接: ^{2}^{a} → ^{2a}
    while _CONSEC_SUP_RE.search(s):
        s = _CONSEC_SUP_RE.sub(r'^{\1\2}', s)

    # 修复导数记号: ^{^{n}^} → ^{(n)}，^({n}^) → ^{(n)} 等
    s = re.sub(r'\^\{\^\{([^}]+)\}\^\}', lambda m: '^{(' + m.group(1) + ')}', s)
    s = re.sub(r'\^\(\^\{([^}]+)\}\^\)', lambda m: '^{(' + m.group(1) + ')}', s)
    # 修复 ⁽...⁾ 产生的 ^{(^{X})} 模式 → ^{(X)}
    s = re.sub(r'\^\{\(\^\{([^}]+)\}\)\}', lambda m: '^{(' + m.group(1) + ')}', s)
    # 下标数字后跟非符号字符时加空格
    s = _SUBSCRIPT_LETTER_RE.sub(r'_{\1} ', s)
    return s


# ── 第二阶段：模式修正 ──────────────────────────────────────────────────

def _convert_limits(s):
    r"""转换极限符号：lim[var→val] → \lim_{var\to val} 等。"""
    out = []
    i = 0
    while i < len(s):
        # 检测 lim[
        if s[i:i+4] == 'lim[' and (i == 0 or (s[i-1] != BS and not ('a' <= s[i-1] <= 'z' or 'A' <= s[i-1] <= 'Z'))):
            # 找到匹配的 ]
            j = i + 4
            depth = 1
            while j < len(s) and depth > 0:
                if s[j] == '[':
                    depth += 1
                elif s[j] == ']':
                    depth -= 1
                j += 1
            if depth == 0:
                inner = s[i+4:j-1]
                # 检查是否是 lim[var→val] 格式（单变量+\to+值）
                if BS + 'to' in inner and len(inner) < 20:
                    # 拆分 var\to val
                    to_pos = inner.find(BS + 'to')
                    var = inner[:to_pos].strip()
                    val = inner[to_pos + len(BS + 'to'):].strip()
                    # 验证 var 是简单变量（1-3个字母+可能的下标）
                    if var and len(var) <= 5 and (var.isalpha() or (var[0].isalpha() and all(c.isalpha() or c in '₀₁₂₃₄₅₆₇₈₉' for c in var))):
                        out.append(BS + 'lim' + BS + 'limits_{' + var + BS + 'to ' + val + '}')
                        i = j
                        continue
                # 不是 lim[var→val] 格式 → 检查后面是否有 (var\to val)
                # 例: lim[expr]=0 (x\to \infty) → \lim_{x\to \infty}[expr]
                after = s[j:]
                m = re.match(r'\s*=?\d*\s*\(([a-zA-Z])' + re.escape(BS + 'to') + r'\s*([^)]+)\)', after)
                if m:
                    var = m.group(1)
                    val = m.group(2).strip()
                    out.append(BS + 'lim' + BS + 'limits_{' + var + BS + 'to ' + val + '}[' + inner + ']')
                    i = j + m.end()
                    continue
                # 没有 (var→val) → 保留原文但加 \lim
                out.append(BS + 'lim[' + inner + ']')
                i = j
                continue
        out.append(s[i])
        i += 1
    return ''.join(out)

def normalize_patterns(s):
    r"""修正常见转换错误。"""
    # 函数名加斜杠：sinx → \sin x
    s = _FUNC_PATTERN.sub(_FUNC_REPL, s)

    # sin2x → \sin 2x（数字参数）
    s = re.sub(
        r'(?<![a-zA-Z' + BS * 2 + r'])(sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|sinh|cosh|tanh|coth)(\d)',
        lambda m: BS + m.group(1) + ' ' + m.group(2), s
    )

    # \sin x → \sin x（修复多余空格）
    s = s.replace(BS + 'sin  x', BS + 'sin x')

    # \int_x^ → \int_{...}^{...}
    s = _INTEGRAL_RE.sub(lambda m: BS + 'int_{' + m.group(1) + (m.group(2) if not m.group(2).startswith('{') else m.group(2)[1:-1]) + '}^', s)

    # 分段函数 {a;b} → \begin{cases} a \\ b \end{cases}
    s = _PIECEWISE_RE.sub(lambda m: BS + 'begin{cases} ' + m.group(1).strip() + ' ' + BS + BS + ' ' + m.group(2).strip() + ' ' + BS + 'end{cases}', s)

    # 极限符号转换（函数式，避免正则转义问题）
    s = _convert_limits(s)

    # \lim[...\to...] → \lim_{...}
    s = _convert_lim_brackets(s)

    # 裸 lim → \lim (不匹配已有 \lim，不匹配紧跟的 ASCII 字母)
    out = []
    i = 0
    while i < len(s):
        if s[i:i+3] == 'lim' and (i == 0 or (s[i-1] != BS and not ('a' <= s[i-1] <= 'z' or 'A' <= s[i-1] <= 'Z'))):
            if i + 3 >= len(s) or s[i+3] not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ':
                # lim 后面跟 _ 时加 \limits 使下标显示在下方
                if i + 3 < len(s) and s[i+3] == '_':
                    out.append(BS + 'lim' + BS + 'limits')
                else:
                    out.append(BS + 'lim')
                i += 3
                continue
        out.append(s[i])
        i += 1
    s = ''.join(out)

    # ^(...) → ^{...}
    s = _convert_caret_parens(s)

    # \sqrt(...) → \sqrt{...}
    s = re.sub(r'\\sqrt\(([^()]*)\)', r'\\sqrt{\1}', s)

    # 求值记号 |_{(X,Y)} → 规范化
    s = _fix_eval_notation(s)

    # Sigma 字符串 → \sum
    s = re.sub(r'(?<![a-zA-Z])Sigma(?![a-zA-Z])', lambda m: BS + 'sum', s)

    # 清理空的 {}（只在特定转换产物处，非全局）
    s = s.replace(BS + 'sin{}', BS + 'sin')

    return s


def _convert_lim_brackets(s):
    r"""Convert \lim[...\to...] → \lim_{...}"""
    while True:
        idx = s.find(BS + 'lim[')
        if idx < 0:
            break
        j = idx + 5
        depth = 1
        while j < len(s) and depth > 0:
            if s[j] == '[':
                depth += 1
            elif s[j] == ']':
                depth -= 1
            j += 1
        if depth == 0:
            inner = s[idx + 5:j - 1]
            if BS + 'to' in inner:
                s = s[:idx] + BS + 'lim' + BS + 'limits_{' + inner + '}' + s[j:]
            else:
                break
        else:
            break
    return s


def _convert_caret_parens(s):
    """^(...) → ^{...}，支持嵌套括号。"""
    out = list(s)
    i = 0
    while i < len(out):
        if i + 1 < len(out) and out[i] == '^' and out[i + 1] == '(':
            j = i + 2
            depth = 1
            while j < len(out) and depth > 0:
                if out[j] == '(':
                    depth += 1
                elif out[j] == ')':
                    depth -= 1
                j += 1
            if depth == 0:
                out[i + 1] = '{'
                out[j - 1] = '}'
                i = j
                continue
        i += 1
    return ''.join(out)


def _fix_eval_notation(s):
    r"""规范化求值记号：|_{(X,Y)}= 和 |_{x=0}。

    处理 Kimi 提取的 Unicode 下标模式：
    |₍₁,₁₎= → |_{(_{1},_{1}_{)= → |_{(1,1)}=
    """
    # 字符级解析求值记号
    result = []
    i = 0
    while i < len(s):
        if s[i:i + 3] == '|_{' and i + 3 < len(s) and s[i + 3] == '(':
            # 收集 |_( 到 ) 之间的所有内容（忽略 _{ } 结构）
            j = i + 4
            content_parts = []
            found_close = False
            while j < len(s):
                ch = s[j]
                if ch == ')':
                    found_close = True
                    j += 1
                    break
                elif ch == '_' and j + 1 < len(s) and s[j + 1] == '{':
                    # 跳过 _{...} 结构，保留内部内容（含花括号）
                    k = j + 2
                    inner = ['_{']
                    brace_depth = 1
                    while k < len(s) and brace_depth > 0:
                        if s[k] == '{':
                            brace_depth += 1
                        elif s[k] == '}':
                            brace_depth -= 1
                        inner.append(s[k])
                        k += 1
                    content_parts.append(''.join(inner))
                    j = k
                else:
                    content_parts.append(ch)
                    j += 1
            if found_close:
                eval_content = ''.join(content_parts)
                result.append('|_{(' + eval_content + ')')
                i = j
                continue
        result.append(s[i])
        i += 1
    return ''.join(result)


# ── 第三阶段：分式转换 ──────────────────────────────────────────────────

def convert_fractions(s):
    """在 $...$ 数学模式内，将 a/b 转为 \frac{a}{b}。"""
    if '$' not in s:
        return s
    result = []
    i = 0
    while i < len(s):
        if s[i] == '$':
            end = s.find('$', i + 1)
            if end < 0:
                result.append(s[i:])
                break
            math = s[i + 1:end]
            math = _convert_frac_in_math(math)
            result.append('$' + math + '$')
            i = end + 1
        else:
            next_d = s.find('$', i)
            if next_d < 0:
                result.append(s[i:])
                break
            result.append(s[i:next_d])
            i = next_d
    return ''.join(result)


def _convert_frac_in_math(math):
    """在数学字符串内转换 a/b → \frac{a}{b}。"""
    result = []
    i = 0
    while i < len(math):
        if math[i] == '/' and i > 0 and i + 1 < len(math):
            # 跳过 \command ) / 模式（这种是 \lim (...) / (...) 不是分式）
            if _is_command_paren_div(math, i):
                result.append(math[i])
                i += 1
                continue
            numer_start, numer = _extract_numerator(math, i)
            denom_end, denom = _extract_denominator(math, i)
            if numer and denom:
                # 移除 result 中已追加的分子字符
                pop_count = i - numer_start
                # 保护：不能 pop 比 result 长度还多
                pop_count = min(pop_count, len(result))
                # 分子带括号时去掉外层括号（\frac 不需要）
                if numer.startswith('(') and numer.endswith(')'):
                    numer = _unwrap_parens(numer)
                for _ in range(pop_count):
                    if result:
                        result.pop()
                result.append(BS + 'frac{' + numer + '}{' + denom + '}')
                i = denom_end
                continue
        result.append(math[i])
        i += 1
    return ''.join(result)


def _is_command_paren_div(math, slash_pos):
    r"""检查 slash 是否在 \command (...) / (...) 模式中（这种不要转分式）。

    例: \lim (x²-xsin(1/x))/(x²+...) — 这种 / 不应转换
    """
    BS = chr(92)
    j = slash_pos - 1
    # 跳过空白
    while j >= 0 and math[j].isspace():
        j -= 1
    if j < 0 or math[j] != ')':
        return False
    # 检查 ( ) 平衡：往左数括号
    depth = 1
    j -= 1
    while j >= 0 and depth > 0:
        if math[j] == ')':
            depth += 1
        elif math[j] == '(':
            depth -= 1
        j -= 1
    if depth != 0:
        return False
    # j 现在在 ( 之前
    # 跳过空白
    while j >= 0 and math[j].isspace():
        j -= 1
    # 必须是字母序列（命令名）
    if j < 0 or not math[j].isascii() or not math[j].isalpha():
        return False
    while j >= 0 and math[j].isascii() and math[j].isalpha():
        j -= 1
    # 必须是反斜杠
    return j >= 0 and math[j] == BS


def _unwrap_parens(s):
    """去除最外层括号，但仅当整段都是同一个括号对时。"""
    if not s.startswith('(') or not s.endswith(')'):
        return s
    depth = 0
    for i, c in enumerate(s):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if depth == 0 and i < len(s) - 1:
            return s  # 括号在中间就闭合了，不拆
    return s[1:-1]


def _extract_numerator(math, slash_pos):
    end = slash_pos
    j = end - 1
    if j < 0:
        return (0, None)
    if math[j] == ')':
        depth = 1
        j -= 1
        start = j
        while j >= 0 and depth > 0:
            if math[j] == ')':
                depth += 1
            elif math[j] == '(':
                depth -= 1
            j -= 1
        if depth != 0:
            return (0, None)
        j += 1  # 现在 j 指向 '('
        # 检查前面是否有 ^{...}
        if j >= 2 and math[j - 2:j] == '^{':
            j -= 2
            while j > 0 and math[j - 1].isalpha():
                j -= 1
            return (j, math[j:end])
        # 返回 ( 的位置，分子包含 ( 让 pop 正确
        return (j, math[j:end])
    elif (math[j].isascii() and math[j].isalpha()) or math[j].isdigit():
        j -= 1
        # 跳过字母/数字/嵌套 ( ) { }
        paren_d = brace_d = 0
        while j >= 0:
            ch = math[j]
            if ch == ')':
                paren_d += 1
            elif ch == '(':
                if paren_d > 0:
                    paren_d -= 1
                else:
                    break
            elif ch == '}':
                brace_d += 1
            elif ch == '{':
                if brace_d > 0:
                    brace_d -= 1
                else:
                    break
            elif ch.isspace() or ch in ',;':
                break
            elif (ch.isascii() and (ch.isalnum() or ch in '+-*/=^_.\\')):
                pass
            else:
                break
            j -= 1
        return (j + 1, math[j + 1:end])
    elif math[j] == '}':
        depth = 1
        j -= 1
        while j >= 0 and depth > 0:
            if math[j] == '}':
                depth += 1
            elif math[j] == '{':
                depth -= 1
            j -= 1
        if depth != 0:
            return (0, None)
        j += 1
        if j >= 1 and math[j - 1] == '^':
            j -= 1
            while j > 0 and math[j - 1].isalpha():
                j -= 1
        elif j >= 2 and math[j - 2:j] == ']{':
            bracket_end = j - 2
            bdepth = 1
            bi = bracket_end - 1
            while bi >= 0 and bdepth > 0:
                if math[bi] == ']':
                    bdepth += 1
                elif math[bi] == '[':
                    bdepth -= 1
                bi -= 1
            if bdepth == 0 and bi >= 1 and math[bi - 1] == '_':
                j = bi - 1
        # 下标 _{...} 不应作为分数分子：_{n+1}/a → 不转换
        if j >= 1 and math[j - 1] == '_':
            return (0, None)
        return (j, math[j:end])
    return (0, None)


def _extract_denominator(math, slash_pos):
    start = slash_pos + 1
    if start >= len(math):
        return (start, None)
    c = math[start]
    if c == '(':
        j = start + 1
        depth = 1
        while j < len(math) and depth > 0:
            if math[j] == '(':
                depth += 1
            elif math[j] == ')':
                depth -= 1
            j += 1
        if depth != 0:
            return (start, None)
        return (j, _unwrap_parens(math[start:j]))
    elif (c.isascii() and c.isalpha()) or c.isdigit():
        j = start + 1
        # 跳过字母/数字/嵌套 ( ) { }
        paren_d = brace_d = 0
        while j < len(math):
            ch = math[j]
            if ch == '(':
                paren_d += 1
            elif ch == ')':
                if paren_d > 0:
                    paren_d -= 1
                else:
                    break  # 不平衡，停止
            elif ch == '{':
                brace_d += 1
            elif ch == '}':
                if brace_d > 0:
                    brace_d -= 1
                else:
                    break
            elif ch.isspace() or ch in ',;':
                break  # 空格/标点停止
            elif (ch.isascii() and (ch.isalnum() or ch in '+-*/=^_.\\')):
                pass  # 继续
            else:
                break
            j += 1
        return (j, math[start:j])
    elif c == '{':
        j = start + 1
        depth = 1
        while j < len(math) and depth > 0:
            if math[j] == '{':
                depth += 1
            elif math[j] == '}':
                depth -= 1
            j += 1
        if depth != 0:
            return (start, None)
        return (j, math[start:j])
    return (start, None)


# ── 第四阶段：智能换行（给裸文本套 $...$）─────────────────────────────

def has_math_content(text):
    """检查文本是否包含需要 $...$ 包裹的数学内容。"""
    if re.search(r'\$[^$]+\$', text):
        return True
    math_indicators = [
        r'[a-z]\^', r'[a-z]_',           # 上标/下标
        r'\d/\d', r'\d+\.\d+',            # 分数/小数
        r'[a-zA-Z]/[a-zA-Z]',             # 裸分式如 (1+ax^{2})/(1+bx)
        r'\b[a-z]\(', r'\)\s*[a-z]',      # 函数调用如 f(x)
        r'\\[a-zA-Z]+',                    # LaTeX 命令如 \theta, \pi
        r'[a-zA-Z]\([^)]*[+\-*/][^)]*\)',  # f(x+y) 等含运算符的函数调用
        r'[a-zA-Z]=[a-zA-Z0-9]',          # 赋值表达式 y=f(x), f(x)=...
        r'\^[{(\[]',                       # ^{...} ^(...)
    ]
    return any(re.search(p, text) for p in math_indicators)


def smart_wrap(text):
    """智能地给裸数学内容套 $...$。

    1. 已有 $：只修复 $ 外面的裸数学内容
    2. 无 $ 但含数学内容：整段包裹
    """
    if not text:
        return text
    # 已有 $，只修复 $ 外面的裸数学内容
    if '$' in text:
        parts = re.split(r'(\$[^$]+\$)', text)
        for i, part in enumerate(parts):
            if not part.startswith('$'):
                wrapped = _wrap_inline_math(part)
                if wrapped != part:
                    parts[i] = wrapped
        return ''.join(parts)
    # 无 $ 的文本：含数学内容时整段包裹
    if has_math_content(text):
        wrapped = _wrap_inline_math(text)
        if wrapped != text:
            return wrapped
        return '$' + text + '$'
    return text


def _wrap_inline_math(text):
    """在中文段落中检测并包裹独立的数学表达式为 $...$。

    处理模式：
    - y=(x-1)^{2}(x-3)^{2}的拐点 → y=$(x-1)^{2}(x-3)^{2}$的拐点
    - 曲线y=2(x-1)^{2} → 曲线$y=2(x-1)^{2}$
    - 设f(x)=x/(1+x+1) → 设$f(x)=x/(1+x+1)$
    """
    if not text or '$' in text:
        return text
    BS = chr(92)

    # 模式1: 表达式含 LaTeX 命令（\alpha, \frac, \int 等）
    if re.search(r'\\[a-zA-Z]+', text):
        return '$' + text + '$'

    # 模式2: 含上标或下标 + 函数调用
    has_power = bool(re.search(r'[a-zA-Z0-9\)\]]\^[{(a-zA-Z0-9+\-]', text))
    has_sub = bool(re.search(r'[a-zA-Z0-9\)\]]_\w', text))
    has_func_call = bool(re.search(r'[a-zA-Z]\([^)]*\)', text))

    if not (has_power or has_sub or has_func_call):
        return text

    # 找到数学表达式的开始和结束位置
    # 策略: 从第一个数学字符开始,直到中文字符/标点结束
    # 数学字符定义: 字母、数字、运算符、括号、上标下标

    start = None
    end = None
    for i, c in enumerate(text):
        is_math = (
            c.isascii() and (c.isalnum() or c in '+-*/=^_().,{}[]\\')
        )
        is_cn = '一' <= c <= '鿿'
        if is_math and start is None:
            start = i
        elif is_cn and start is not None and end is None:
            end = i
            break

    if start is None:
        return text

    # 简化策略：用 token 序列匹配数学区段
    # 触发条件: 起始字符是字母/数字,后续可包含 { } ( ) ^ _ 字母 数字 + - * / =
    # 括号匹配但限制递归深度

    result = []
    pos = 0
    while pos < len(text):
        c = text[pos]
        # 中文或中文标点：原样输出
        if '一' <= c <= '鿿' or c in '，。；：、？！':
            result.append(c)
            pos += 1
            continue

        # ASCII 字母或数字：可能是数学区段起点
        if c.isascii() and (c.isalpha() or c.isdigit()):
            seg_start = pos
            seg_end = pos
            paren_d, brace_d, bracket_d = 0, 0, 0
            while seg_end < len(text):
                ch = text[seg_end]
                # 中文中段终止
                if '一' <= ch <= '鿿':
                    break
                # 中文标点终止
                if ch in '，。；：、？！':
                    break
                # ASCII 数学字符继续
                if ch.isascii():
                    if ch.isalnum() or ch in '+-*/=._\\':
                        seg_end += 1
                        continue
                    if ch in '^_':
                        seg_end += 1
                        # 上标/下标后允许一个 {} 块
                        if seg_end < len(text) and text[seg_end] in '{(':
                            open_c = text[seg_end]
                            close_c = '}' if open_c == '{' else ')'
                            depth = 1
                            seg_end += 1
                            while seg_end < len(text) and depth > 0:
                                if text[seg_end] == open_c:
                                    depth += 1
                                elif text[seg_end] == close_c:
                                    depth -= 1
                                seg_end += 1
                        continue
                    if ch == '(':
                        paren_d += 1
                        seg_end += 1
                        continue
                    if ch == ')':
                        if paren_d > 0:
                            paren_d -= 1
                            seg_end += 1
                            continue
                        break
                    if ch == '{':
                        brace_d += 1
                        seg_end += 1
                        continue
                    if ch == '}':
                        if brace_d > 0:
                            brace_d -= 1
                            seg_end += 1
                            continue
                        break
                    if ch == '[':
                        bracket_d += 1
                        seg_end += 1
                        continue
                    if ch == ']':
                        if bracket_d > 0:
                            bracket_d -= 1
                            seg_end += 1
                            continue
                        break
                    # 其他 ASCII 字符 (标点如 , ;) 终止
                    break
                else:
                    break

            segment = text[seg_start:seg_end]
            # 修剪尾部运算符
            while segment and segment[-1] in '+-*/=':
                segment = segment[:-1]
            # 修剪不平衡尾部括号
            while segment:
                last = segment[-1]
                if last == ')' and paren_d > 0:
                    segment = segment[:-1]
                    paren_d -= 1
                elif last == '}' and brace_d > 0:
                    segment = segment[:-1]
                    brace_d -= 1
                elif last == ']' and bracket_d > 0:
                    segment = segment[:-1]
                    bracket_d -= 1
                else:
                    break

            if len(segment) >= 2:
                result.append('$' + segment + '$')
            else:
                result.append(segment)
            pos = seg_start + len(segment)
        else:
            # 其他字符（如标点、空格）原样输出
            result.append(c)
            pos += 1

    return ''.join(result)


# ── 主流程 ──────────────────────────────────────────────────────────────

def convert_question(q):
    """转换单道题目的所有文本字段。"""
    q['content'] = _convert_text(q['content'])
    if q.get('options') and isinstance(q['options'], dict):
        for k in q['options']:
            q['options'][k] = _convert_text(q['options'][k])
    if q.get('sub_questions'):
        for idx, sq in enumerate(q['sub_questions']):
            if isinstance(sq, str):
                q['sub_questions'][idx] = _convert_text(sq)


def _convert_text(text):
    """单个文本字段的完整转换流程。"""
    text = unicode_to_latex(text)
    text = normalize_patterns(text)
    text = smart_wrap(text)
    return text


def _fix_extraction_errors(math):
    r"""修复 vision API 提取时常见的命令粘连错误。

    - \li → \lim （最常见，因为 \lim 后面通常是空格）
    - \xif → \xi f （希腊字母后忘记空格）
    - \etaf → \eta f
    - \alphaf → \alpha f
    - \betaf → \beta f
    - \gammag → \gamma g
    - 其他 greek letter + letter 模式
    - \lim + 空格 + its → \limits （vision API 拆命令错误）
    """
    BS = chr(92)
    # \lim + 任意空白 + its → \limits（vision API 把 \limits 拆成 \lim+its）
    math = re.sub(r'\\lim[\s ]+its(?![a-zA-Z])', lambda m: BS + 'limits', math)
    # \lim + 任意空白 + its → （容错上面匹配失败的情况）
    # \li + 字母 → \lim + 字母（要保留 \lim 后面紧跟的字母当参数）
    # 只在 \li 后不是 m 时修正
    math = re.sub(r'\\li(?!m)(?=[a-zA-Z])', lambda m: BS + 'lim', math)
    # \li + 空格 → \lim + 空格（最常见的"求极限"题场景）
    math = re.sub(r'\\li ', lambda m: BS + 'lim ', math)
    # \xi + 字母 → \xi 字母
    for greek in ['xi', 'eta', 'alpha', 'beta', 'gamma', 'delta', 'theta',
                  'lambda', 'mu', 'sigma', 'omega', 'rho', 'tau', 'varphi']:
        math = re.sub(r'\\' + greek + r'(?=[a-zA-Z])',
                      lambda m, g=greek: BS + g + ' ', math)
    return math


def _fix_cmd_spacing(math):
    r"""修复 LaTeX 命令后直接跟字母（KaTeX 会把 \leqx 当做未知命令）。"""
    BS = chr(92)
    _CMDS = sorted([
        'leqslant', 'geqslant', 'leqq', 'geqq', 'leq', 'geq',
        'neq', 'approx', 'equiv', 'propto', 'cdot', 'times',
        'pm', 'mp', 'Delta', 'Sigma', 'Pi', 'Gamma', 'Lambda', 'Theta',
        'forall', 'exists', 'notin', 'Rightarrow', 'Leftrightarrow',
        'infty', 'pi', 'alpha', 'beta', 'gamma', 'delta', 'varepsilon',
        'varphi', 'theta', 'lambda', 'mu', 'sigma', 'omega', 'nabla',
        'partial', 'iint', 'oint', 'sum', 'prod', 'cdot',
        'operatorname', 'mathrm', 'text',
        'sinh', 'cosh', 'tanh', 'arcsin', 'arccos', 'arctan',
        'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
        'log', 'det', 'dim', 'ker', 'deg', 'gcd',
        'max', 'min', 'sup', 'inf', 'circ',
        'lim', 'int', 'ln', 'exp', 'to', 'in',
    ], key=len, reverse=True)
    _CMD_SET = set(_CMDS)
    result = []
    i = 0
    while i < len(math):
        if math[i] == BS and i + 1 < len(math) and math[i + 1].isascii() and math[i + 1].isalpha():
            # 提取完整命令名
            j = i + 1
            while j < len(math) and math[j].isascii() and math[j].isalpha():
                j += 1
            cmd = math[i + 1:j]
            # 在已知命令中找最佳匹配（最长前缀）
            best = None
            for known in _CMDS:
                if cmd == known or cmd.startswith(known):
                    best = known
                    break
            if best and best in _CMD_SET:
                if cmd == best:
                    # 完全匹配：检查后面是否紧跟字母
                    if j < len(math) and math[j].isascii() and math[j].isalpha():
                        result.append(BS + best + ' ')
                    else:
                        result.append(BS + best)
                    i = j
                else:
                    # 前缀匹配（如 leqx 匹配 leq）：拆分，加空格
                    result.append(BS + best + ' ')
                    i = i + 1 + len(best)
            else:
                # 未知命令，原样保留
                result.append(math[i:j])
                i = j
        else:
            result.append(math[i])
            i += 1
    return ''.join(result)


def _clean_katex(s):
    """清理文本使其能被 KaTeX 正确渲染。"""
    def _fix_math_block(m):
        math = m.group(1)
        # 跳过包含 \begin{cases} 的块（其中 \\ 是合法的换行符）
        if BS + 'begin{cases}' in math:
            math = re.sub(r'__+', lambda m2: (BS + '_') * len(m2.group()), math)
            # 修复命令后缺空格（\begin{cases} 中也需要）
            math = _fix_cmd_spacing(math)
            return '$' + math + '$'
        # 修复 vision API 提取错误（缺空格导致的命令粘连）
        math = _fix_extraction_errors(math)
        # 双反斜杠 → 单反斜杠（KaTeX 中 \\ 是换行，通常在行内公式中是错误的）
        math = math.replace(BS * 2, BS)
        # frac{pi} → frac{\pi}
        math = math.replace('frac{pi}', 'frac{' + BS + 'pi}')
        # frac{neq → frac{\neq （常见提取错误）
        math = re.sub(r'frac\{neq', 'frac{' + BS + 'neq', math)
        # 连续下划线（填空题 _____）→ 转义为 \_（KaTeX 中 __ 会报错）
        math = re.sub(r'__+', lambda m2: (BS + '_') * len(m2.group()), math)
        # 修复 double subscript：_{n}_{+}_{1}  →  _{n+1}（合并相邻下标块）
        # 单次匹配 _{A}_{B} → _{AB}，迭代直到无变化
        prev = None
        while prev != math:
            prev = math
            math = re.sub(r'_\{([^{}]+)\}_\{([^{}]+)\}', r'_{\1\2}', math)
        # 修复 _\frac 等错误：下划线紧跟 LaTeX 命令 → 分隔符，去掉下划线
        math = re.sub(r'_(\\(?:frac|sqrt|sin|cos|tan|log|ln|lim|sum|int|prod|max|min|sup|inf|exp|det|dim|ker|deg|gcd|limsup|liminf))\b',
                      r'\1', math)
        # 修复未闭合的求值下标：|_{(a,b)  →  |_{(a,b)}
        math = re.sub(r'\|_\{\(([^)]+)\)(?!\})', r'|_{(\1)}', math)
        # 修复积分绝对值：\int_{0}^|^{x}|  →  \int_{0}^{|x|}
        math = re.sub(r'\^\|(\^\{[^}]+\})\|', r'^{|\1|}', math)
        # 修复裸 \sqrt（无参数）：\sqrt3 → \sqrt{3}
        math = re.sub(r'\\sqrt(?!\s*\{)(\w)', lambda m: BS + 'sqrt{' + m.group(1) + '}', math)
        # \sqrt|x| → \sqrt{|x|}
        math = re.sub(r'\\sqrt\|([^|]+)\|', lambda m: BS + 'sqrt{|' + m.group(1) + '|}', math)
        # 仍有裸 \sqrt 的兜底
        math = re.sub(r'\\sqrt(?!\s*\{)', lambda m: BS + 'sqrt{}', math)
        # 修复命令后缺空格
        math = _fix_cmd_spacing(math)
        return '$' + math + '$'
    return re.sub(r'\$([^$]+)\$', _fix_math_block, s)


def _post_fix(data):
    """后处理：批量修复 LLM 审核发现的问题。"""
    for q in data:
        # 1. 题型统一：解答题 → 计算题
        if q.get('type') == '解答题':
            q['type'] = '计算题'

        # 2. 选项值去掉前缀 "A. "
        opts = q.get('options')
        if opts and isinstance(opts, dict):
            new_opts = {}
            for k, v in opts.items():
                new_v = re.sub(r'^[A-F][.．、]\s*', '', v)
                new_opts[k] = new_v
            q['options'] = new_opts

        def _fix_str(s):
            BS = chr(92)
            # 3. 空 \sqrt{} 后跟字母：\sqrt{}x → \sqrt{x}
            s = re.sub(re.escape(BS + 'sqrt{}') + r'(\w)',
                       lambda m: BS + 'sqrt{' + m.group(1) + '}', s)

            # 3b. \sqrt{}[expr] → \sqrt{expr}（方括号作括号用）
            while BS + 'sqrt{}[' in s:
                idx = s.find(BS + 'sqrt{}[')
                start = idx + len(BS + 'sqrt{}[')
                depth, end = 0, -1
                for i in range(start, len(s)):
                    if s[i] == '[': depth += 1
                    elif s[i] == ']':
                        if depth == 0:
                            end = i
                            break
                        depth -= 1
                if end > 0:
                    s = s[:idx] + BS + 'sqrt{' + s[start:end] + '}' + s[end+1:]
                else:
                    break

            # 4. f\frac{a}{b} → f \frac{a}{b}（加空格，避免歧义）
            s = re.sub(r'([a-zA-Z])' + re.escape(BS) + r'frac\{',
                       lambda m: m.group(1) + ' ' + BS + 'frac{', s)

            # 5. 偏导数 f\gamma' → f_{y}'
            s = s.replace("f" + BS + "gamma'", "f_{y}'")
            s = s.replace("f" + BS + "gamma''", "f_{y}''")

            # 6. \Sigma → \sum
            s = s.replace(BS + 'Sigma', BS + 'sum')

            return s

        q['content'] = _fix_str(q.get('content', ''))
        if q.get('options') and isinstance(q['options'], dict):
            q['options'] = {k: _fix_str(v) for k, v in q['options'].items()}
        if q.get('sub_questions'):
            q['sub_questions'] = [_fix_str(sq) if isinstance(sq, str) else sq
                                  for sq in q['sub_questions']]


def run(frac=True):
    """运行完整转换流程。

    - 从备份恢复（备份是上游 vision API 的输出）
    - 跳过 manually_fixed=True 的题目（人工修复过的不再被覆盖）
    - 分式转换、KaTeX 清理、后处理
    - 保存到 questions.json
    """
    # 从备份恢复
    with open(BACKUP_JSON, encoding='utf-8') as f:
        data = json.load(f)

    # 标记转换前的题目（用于增量备份 + 手动修复检测）
    fixed_ids = {q['id'] for q in data if q.get('manually_fixed')}

    # 转换（跳过人工修复的题目）
    skipped = 0
    for q in data:
        if q.get('manually_fixed'):
            skipped += 1
            continue
        convert_question(q)

    # 分式转换
    if frac:
        for q in data:
            if q.get('manually_fixed'):
                continue
            q['content'] = convert_fractions(q['content'])
            if q.get('options') and isinstance(q['options'], dict):
                for k in q['options']:
                    q['options'][k] = convert_fractions(q['options'][k])
            if q.get('sub_questions'):
                for idx, sq in enumerate(q['sub_questions']):
                    if isinstance(sq, str):
                        q['sub_questions'][idx] = convert_fractions(sq)

    # 清理：修复 KaTeX 无法渲染的问题
    for q in data:
        if q.get('manually_fixed'):
            continue
        q['content'] = _clean_katex(q['content'])
        if q.get('options') and isinstance(q['options'], dict):
            for k in q['options']:
                q['options'][k] = _clean_katex(q['options'][k])
        if q.get('sub_questions'):
            for idx, sq in enumerate(q['sub_questions']):
                if isinstance(sq, str):
                    q['sub_questions'][idx] = _clean_katex(sq)

    # ── 后处理：批量修复已知问题 ──
    _post_fix(data)

    # 保存
    with open(QUESTIONS_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'转换完成：{len(data)} 题（跳过 {skipped} 道人工修复）')

    # 验证
    issues = 0
    for q in data:
        c = q['content']
        for m in re.finditer(r'\$([^$]+)\$', c):
            math = m.group(1)
            if re.search(r'\^\(', math):
                issues += 1
                break
    print(f'剩余 ^(...) 问题：{issues}')

    # 展示前 3 题
    for q in data[:3]:
        print(f"\nQ{q['id']}: {q['content'][:120]}")

    return data


if __name__ == '__main__':
    frac = '--no-frac' not in sys.argv
    run(frac=frac)
