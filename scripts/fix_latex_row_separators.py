#!/usr/bin/env python3
"""
修复 LaTeX 环境（cases、aligned、matrix 等）中被吞掉的 `\\` 换行符。

提取/转义过程中经常出现 `\\\\` 变成 `\\` 的情况，导致 cases 多行显示成一行。
用法：
  python scripts/fix_latex_row_separators.py --dry-run
  python scripts/fix_latex_row_separators.py --run
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

# 常见 LaTeX 命令白名单；遇到这些开头的反斜杠时，不应把它当成 stray 换行符
KNOWN_COMMANDS = {
    # 希腊字母
    'alpha','beta','gamma','delta','epsilon','varepsilon','zeta','eta','theta','vartheta',
    'iota','kappa','lambda','mu','nu','xi','pi','varpi','rho','varrho','sigma','varsigma',
    'tau','upsilon','phi','varphi','chi','psi','omega','Gamma','Delta','Theta','Lambda',
    'Xi','Pi','Sigma','Upsilon','Phi','Psi','Omega',
    # 函数/运算符
    'sin','cos','tan','cot','sec','csc','arcsin','arccos','arctan','sinh','cosh','tanh',
    'log','ln','exp','arg','det','dim','gcd','hom','ker','lim','liminf','limsup','max',
    'min','Pr','sup','inf','operatorname','operatorname*','operatornamewithlimits',
    'varlimsup','varliminf','varinjlim','varprojlim','injlim','projlim','Tr','tr','rank',
    'sgn','argmin','argmax',
    # 关系/逻辑
    'pm','mp','times','div','cdot','ldots','cdots','vdots','ddots','le','ge','leq','geq',
    'ne','neq','equiv','approx','sim','simeq','propto','perp','parallel','mid','nmid','in',
    'notin','subset','supset','subseteq','supseteq','cup','cap','setminus','emptyset',
    'infty','forall','exists','nexists','Rightarrow','Leftarrow','rightarrow','leftarrow',
    'leftrightarrow','Longleftrightarrow','implies','iff','mapsto','to','gets','land','lor',
    'lnot','neg','vee','wedge','cdotp','colon','dots','dotsc','dotsb','dotsm','dotso',
    'hdots','ldotp',
    # 结构命令
    'frac','dfrac','tfrac','binom','sqrt','root','int','iint','iiint','oint','sum','prod',
    'bigcup','bigcap','bigvee','bigwedge','bigoplus','bigotimes','bigsqcup','biguplus',
    'limits','nolimits','displaylimits','overbrace','underbrace','overset','underset',
    'stackrel','text','mathrm','mathit','mathbf','boldsymbol','mathsf','mathtt','mathbb',
    'mathcal','mathfrak','mathscr','tag','label','ref','eqref','pageref','nameref','cite',
    'begin','end','left','right','middle','bigl','bigr','Bigl','Bigr','biggl','biggr',
    'Biggl','Biggr','langle','rangle','lceil','rceil','lfloor','rfloor','vert','Vert',
    'backslash','quad','qquad','phantom','vphantom','hphantom','smash','mathchoice',
    'mathpalette','mathop','mathbin','mathrel','mathord','mathopen','mathclose','mathpunct',
    'mathinner','vcenter','strut','mathstrut','llap','rlap','smash','lower','raise',
    'moveleft','moveright','mspace','kern','mkern','hspace','vspace','mskip','muskip',
    'textstyle','displaystyle','scriptstyle','scriptscriptstyle','pmb','bmod','pmod','mod',
    'pod','big','Big','bigg','Bigg','mbox','hbox','vbox','textnormal','textrm','textmd',
    'textlf','textsc','textsl','textup','emph','textbf','textit','texttt','underline',
    'overline','mathring','textcircled','allowbreak','nobreak','notag','nonumber','newline',
    'linebreak','nolinebreak','pagebreak','nopagebreak','allowdisplaybreaks','displaybreak',
    # 上下标/箭头/重音
    'bar','overline','underline','overbrace','underbrace','overset','underset','stackrel',
    'vec','widevec','hat','widehat','tilde','widetilde','dot','ddot','dddot','ddddot',
    'check','breve','acute','grave','mathring','overleftarrow','overrightarrow',
    'overleftrightarrow','underleftarrow','underrightarrow','underleftrightarrow',
    'xleftarrow','xrightarrow','xLeftarrow','xRightarrow','xleftrightarrow','xLeftrightarrow',
    # 二元关系补充
    'll','gg','lll','ggg','lesssim','gtrsim','lessgtr','gtrless','prec','succ','preceq',
    'succeq','precsim','succsim','precnsim','succnsim','ni','nsubseteq','nsupseteq',
    'sqsubset','sqsupset','sqsubseteq','sqsupseteq','uplus','sqcap','sqcup','amalg',
    'dagger','ddagger','wr','otimes','oplus','ominus','oslash','odot','circ','bullet',
    'diamond','bigcirc','ast','star','bigstar',
    # 括号/箭头
    'lgroup','rgroup','lmoustache','rmoustache','arrowvert','Arrowvert','bracevert',
    'uparrow','Uparrow','downarrow','Downarrow','updownarrow','Updownarrow','hookrightarrow',
    'hookleftarrow','rightleftharpoons','leftrightharpoons','rightharpoonup','rightharpoondown',
    'leftharpoonup','leftharpoondown','searrow','swarrow','nearrow','nwarrow','leadsto',
    'longrightarrow','longleftarrow','Longrightarrow','Longleftarrow','longleftrightarrow',
    'Longleftrightarrow',
    # 大型运算符/积分
    'coprod','idotsint','intop','ointop','smallint','bigodot','iiiint',
    # 间距
    'medspace','thickspace','thinspace','negthinspace','negmedspace','negthickspace',
    'medmuskip','thickmuskip','thinmuskip','hfil','vfil','hfill','vfill','hss','vss',
    'hfilneg','vfilneg','nobreakspace','hskip','vskip','raisebox',
    # 环境名本身
    'cases','aligned','align','array','matrix','pmatrix','bmatrix','vmatrix','Bmatrix',
    'smallmatrix','subarray','gather','gathered','multline','split','eqnarray','darray',
    'equation','flalign','alignat','xalignat','xxalignat','numcases','subnumcases',
    'intertext','shortintertext',
    # 其他常用
    'newcommand','renewcommand','DeclareMathOperator','operatorname','operatorname*',
    'atop','choose','brack','brace','sp','sb',
    # 特殊字母
    'Re','Im','aleph','beth','gimel','daleth','hbar','hslash','imath','jmath','ell','wp',
    'mho','partial','nabla','surd','top','bot','vdash','dashv','models','Vdash','Vvdash',
    'vDash','nvdash','ndashv','nparallel','asymp','cong','doteq','nsim',
    # 集合/几何
    'angle','measuredangle','sphericalangle','triangle','triangledown','square',
    'blacksquare','lozenge','blacklozenge','clubsuit','diamondsuit','heartsuit','spadesuit',
}

_ALT = '|'.join(re.escape(k) for k in KNOWN_COMMANDS)
# stray 反斜杠：不是已知命令、也不是转义特殊字符、也不是反斜杠-空格（空格单独处理）
_STRAY_RE = re.compile(
    r'(?<!\\)\\(?!' + _ALT + r'\b|[\{\}\[\]\(\)\|_\^\\\\\$%\&\#\@\~\`\,\.\;\:\!\+\-\=\<\>\/ ])'
)
_ENV_NAMES = (
    'cases|aligned|align|array|matrix|pmatrix|bmatrix|vmatrix|Bmatrix|smallmatrix|'
    'subarray|gather|gathered|multline|split|eqnarray|darray'
)
_ENV_RE = re.compile(r'\\begin\{(' + _ENV_NAMES + r')\}(.*?)\\end\{\1\}', re.S)


def _next_double_backslash(block: str, idx: int) -> int:
    m = re.search(r'\\\\', block[idx:])
    return idx + m.start() if m else len(block)


def _fix_env_block(block: str) -> str:
    has_amp = '&' in block
    # 1) 反斜杠+空格：只有在它开启一个新行时才补成 \\
    out = []
    i = 0
    while i < len(block):
        if block.startswith('\\ ', i) and (i == 0 or block[i - 1] != '\\'):
            nxt = _next_double_backslash(block, i + 2)
            segment = block[i + 2:nxt]
            # 无 & 的环境（如参数方程）全部视为换行；有 & 时，若到下一个已有换行符之间出现 &，说明是新行
            is_row_sep = (not has_amp) or ('&' in segment)
            if is_row_sep:
                out.append('\\\\ ')
                i += 2
                continue
        out.append(block[i])
        i += 1
    block = ''.join(out)
    # 2) 反斜杠后直接跟非命令字符（如 \y、\6）时补成 \\
    block = _STRAY_RE.sub(lambda m: '\\\\' + m.group(0)[1:], block)
    return block


def fix_text(text: str) -> str:
    return _ENV_RE.sub(lambda m: _fix_env_block(m.group(0)), text)


def run(book_dir: Path, dry_run: bool):
    path = book_dir / 'questions.json'
    if not path.exists():
        for alt in book_dir.glob('*.json'):
            if '题目' in alt.name or 'questions' in alt.name.lower():
                path = alt
                break
    if not path.exists():
        print(f'[跳过] 找不到 {book_dir} 的题目 JSON')
        return

    data = json.loads(path.read_text(encoding='utf-8'))
    changed = 0
    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            old = q.get('content', '')
            new = fix_text(old)
            if new != old:
                q['content'] = new
                changed += 1

    print(f'[{book_dir.name}] 修复 {changed} 道题目')
    if changed and not dry_run:
        bak = path.with_suffix(path.suffix + '.bak.row_fix')
        shutil.copy2(path, bak)
        write_json_atomic(path, data, indent=2)
        print(f'  已备份: {bak}')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', action='store_true', help='写入修改（默认仅打印）')
    args = p.parse_args()

    run(ROOT / '660题', not args.run)
    run(ROOT / '880题', not args.run)
    run(ROOT / '1000题', not args.run)
    run(ROOT / '大学深埋', not args.run)


if __name__ == '__main__':
    main()
