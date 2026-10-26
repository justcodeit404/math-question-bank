"""PDF 做题本导出：数学当前筛选集合与纯题目渲染契约。"""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "880题" / "math-bank" / "index.html"
TEMPLATE = ROOT / "templates" / "math-bank.html"


def _function(source: str, name: str) -> str:
    start = source.index("function %s(" % name)
    end = source.index("\n}\n", start)
    return source[start:end] + "\n}\n"


def test_workbook_renderer_excludes_answers_and_saved_fill_input():
    source = VIEWER.read_text(encoding="utf-8")
    functions = "\n".join(
        _function(source, name)
        for name in (
            "questionBodyHtml",
            "workbookQuestionHtml",
            "exportFilteredWorkbook",
            "renderQuestionBody",
        )
    )
    program = r"""
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function imageHtml(ref) { return '<img src="' + ref + '">'; }
function renderOptionsHtml(q) {
  return '<div class="q-options">' + Object.entries(q.options || {})
    .map(([key, value]) => key + '. ' + value).join('；') + '</div>';
}
function renderSubHtml(q) {
  return (q.sub_questions || []).map((text, i) => '<div>(' + (i + 1) + ') ' + text + '</div>').join('');
}
let answerCalls = 0;
let myAnswerCalls = 0;
function answerHtml() {
  answerCalls++;
  return '<div>SECRET_ANSWER SECRET_EXPLANATION SECRET_ANSWER_IMAGE</div>';
}
function myAnswerHtml() { myAnswerCalls++; return '<input value="SECRET_MY_ANSWER">'; }
function getMyAnswer() { throw new Error('saved answer read'); }
function saveMyAnswer() { throw new Error('answer input bound'); }
function renderKatex() {}
function recordKatexErrors() {}
function alert(message) { throw new Error(message); }
function makeContainer() {
  const qtext = { raw: '', set textContent(value) { this.raw = value; } };
  return {
    _html: '',
    set innerHTML(value) { this._html = value; },
    get innerHTML() {
      return this._html.replace(
        '<div class="q-text" data-role="qtext"></div>',
        '<div class="q-text" data-role="qtext">' + qtext.raw + '</div>'
      );
    },
    querySelector(selector) { return selector === '[data-role="qtext"]' ? qtext : null; },
    querySelectorAll() { return []; },
  };
}
let lastContainer = null;
const document = {
  title: '数学 880',
  createElement() { lastContainer = makeContainer(); return lastContainer; },
};
let captured = null;
const window = { ViewerPdfExport: { open(options) { captured = options; } } };
const fixture = {
  uid: '880-1', id: '1', chapter: '第一章 函数', page: 8, type: '填空题',
  content: '数学题干 $x^2$', has_image: true, image_ref: 'question.png',
  options: { A: '甲', B: '乙' }, sub_questions: ['子题正文'],
  answer: 'SECRET_ANSWER', explanation: 'SECRET_EXPLANATION',
  answer_ref: 'SECRET_ANSWER_IMAGE', answer_structured: 'SECRET_ANSWER',
};
const second = Object.assign({}, fixture, { id: '2', uid: '880-2', content: '先排版题' });
const filteredQuestions = [second, fixture];
""" + functions + r"""
const normal = questionBodyHtml(fixture);
if (!normal.includes('SECRET_ANSWER') || !normal.includes('SECRET_MY_ANSWER')) {
  throw new Error('normal detail rendering regressed');
}
answerCalls = 0;
myAnswerCalls = 0;
const html = workbookQuestionHtml(fixture);
for (const expected of ['数学题干 $x^2$', 'question.png', 'A. 甲', '子题正文', '第一章 函数']) {
  if (!html.includes(expected)) throw new Error('question content missing: ' + expected);
}
if (html.includes('SECRET_') || html.includes('q-myanswer-input')) {
  throw new Error('answer or saved input leaked');
}
if (answerCalls || myAnswerCalls) throw new Error('answer renderer called in workbook mode');
exportFilteredWorkbook();
if (!captured || captured.questions !== filteredQuestions) throw new Error('wrong filtered question set');
if (captured.questions.map((q) => q.id).join(',') !== '2,1') throw new Error('order changed');
if (captured.title !== '数学 880 · 当前筛选') throw new Error('wrong title');
if (captured.renderQuestion(fixture).includes('SECRET_')) throw new Error('renderer leaked');
console.log('ok');
"""
    result = subprocess.run(
        ["node", "-e", program], text=True, encoding="utf-8", capture_output=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_all_generated_books_have_workbook_wiring():
    for book in ("660题", "880题", "1000题", "大学深埋"):
        source = (ROOT / book / "math-bank" / "index.html").read_text(encoding="utf-8")
        assert 'id="btnExportWorkbook"' in source, book
        assert "pdf-export.js?v=" in source, book
        assert "hideMyAnswer: true" in source, book
        assert "questions: filteredQuestions" in source, book
    generator = (ROOT / "scripts" / "generate_viewer.py").read_text(encoding="utf-8")
    assert "'pdf-export.js'," in generator
    assert "btnExportWorkbook" in TEMPLATE.read_text(encoding="utf-8")
