## 临时脚本说明（temp/）

### auto_audit.py
视觉模型自动审核脚本，调用 ModelScope Qwen3-VL-8B-Instruct API 审核题库。

**功能**：随机抽页，每页多题一起审，生成 HTML 报告。

**注意**：该 API 有日配额限制，配额耗尽后所有请求返回 429，需等次日刷新。

```bash
python auto_audit.py --bank "1000题" --n 30 --output "审核报告.html"
```

### scan_quality.py
规则驱动题库质量扫描，无需 API，纯本地规则检测 LaTeX 错误/乱码/选项缺失等问题。

```bash
python scan_quality.py --bank "1000题"
```



## 项目结构

```
数学题库/
├── index.html                  # 主页（题库选择）
├── 启动题库.bat                # 双击启动服务器并打开主页
├── CLAUDE.md
├── scripts/                    # 构建工具（提取、裁剪、重建）
│   ├── rebuild_from_sources.py # 从原始源重建 questions.json
│   ├── apply_crops.py          # 裁剪有图题
│   ├── img_boxes.json          # 裁剪坐标
│   └── *.mjs                   # vision agent 提取脚本
├── 大学深埋/
│   ├── math-bank/
│   │   ├── index.html          # 交互式题库页面
│   │   └── data.js             # 题目数据（自动生成）
│   └── pdf_images/             # PDF 页面渲染图
└── 1000题/
    ├── math-bank/
    │   ├── index.html          # 交互式题库页面
    │   ├── data.js             # 题目数据（自动生成）
    │   └── images/             # 裁剪后的题目图片
    ├── pdf_images/             # PDF 页面渲染图
    └── questions.json          # 最终题目数据
└── 880题/
    ├── math-bank/
    │   ├── index.html          # 交互式题库页面
    │   └── data.js             # 题目数据（自动生成）
    └── pdf_images/             # PDF 页面渲染图
```

## 技术栈

- 前端：纯 HTML + CSS + JS，KaTeX 渲染数学公式
- 后端：`python -m http.server 8123`（静态文件服务）
- 数据：原始提取文件 → `rebuild_from_sources.py` → `questions.json` → `data.js`

## 关键命令

```bash
# 启动服务器（从数学题库目录，或双击 启动题库.bat）
python -m http.server 8123

# 从原始源重建 questions.json（1000题）
python scripts/rebuild_from_sources.py

# 裁剪有图题的图片（1000题）
python scripts/apply_crops.py
```

## 题库页面模板

两个题库页面共用同一个模板，差异仅在 3 个占位符：
- `__TITLE__` — `<title>` 标签
- `__SIDEBAR_TITLE__` — 侧边栏标题
- `__SIDEBAR_SUBTITLE__` — 侧边栏副标题

模板位置：`~/.claude/skills/pdf-to-interactive-bank/references/index.html.template`

更新模板后，需重新生成两个题库页面。

## 处理扫描件 PDF 的注意事项

详见 `~/.claude/skills/pdf-to-interactive-bank/references/scanned-pdf-guide.md`

核心要点：
1. 用 vision agent 提取，不用 OCR
2. has_image 只在内容提到"如图"时才设为 true
3. 去重用 `(chapter, id)`，不是 `(id, page)`
4. 组装脚本只从原始提取文件读，不依赖 questions.json
5. 测试卷用原始 chapter 字段，不用页码映射

## 经验与改进

在项目工作过程中，遇到以下情况时应主动将经验写入 skill 参考文件（`~/.claude/skills/pdf-to-interactive-bank/references/`）：

1. **踩坑记录**：遇到的坑（如页面级节检测不准、PDF 文本提取的特殊格式等）及其根因和修复方案
2. **更高效的方案**：发现比当前 skill 文档中描述的更优做法时，更新对应参考文件
3. **验证手段**：有效的验证和排查方法（如逐位置对比、逐页标记计数等）
4. **配置相关**：chapter ranges、page offset、API 配置等容易出错的配置项，记录正确的值和易错点

不需要记录的：一次性调试代码、已被修复的 bug 的中间状态、纯临时的排查脚本。

## 添加新题库

1. 在对应目录下处理 PDF（渲染 → 提取 → 清理 → 组装）
2. 从模板生成 `math-bank/index.html`，替换 3 个占位符
3. 生成 `data.js`
4. 在 `index.html`（主页）中添加新的 `book-card`
