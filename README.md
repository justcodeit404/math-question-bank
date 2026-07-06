# 考研数学题库

本地静态数学题库系统，支持题目浏览、搜索、练习、抽检和质检。

## 快速开始

双击以下批处理文件启动：

- `启动题库.bat` — 打开首页，选择题库
- `启动抽检.bat` — 随机抽取题目进行人工审核

启动后会自动在后台启动一个本地 HTTP 服务器（端口 8123），关闭窗口时只停止该服务器，不会影响其他 Python 进程。

## 项目结构

```
.
├── index.html                      # 首页
├── 660题/                          # 660 题题库
├── 880题/                          # 880 题题库
├── 1000题/                         # 1000 题题库
├── 大学深埋/                        # 大学深埋做题本
│   └── math-bank/index.html        # 各题库 viewer
├── scripts/                        # 核心脚本
│   ├── normalize_schema.py         # 统一 questions.json schema
│   ├── generate_data_js.py         # 生成 math-bank/data.js
│   ├── generate_viewer.py          # 生成 math-bank/index.html
│   ├── quality_check.py            # 生成质量报告
│   └── server.py                   # 本地 HTTP 服务器
├── templates/                      # 统一模板
│   └── math-bank.html              # 题库 viewer 模板
├── schemas/                        # 数据规范
│   └── question-v1.md              # 统一 JSON schema 说明
├── temp/                           # 临时文件/调试产物
│   ├── audit.html                  # 抽检页面
│   ├── reports/题库检测器.html      # 题库检测器
│   └── backups/                    # 归档备份
└── requirements.txt                # Python 依赖
```

## 核心脚本用法

### 统一所有题库数据格式

```bash
python scripts/normalize_schema.py
```

会把四个 `questions.json` 转成统一格式，并为每道题生成全局唯一的 `uid`。

### 重新生成 viewer 数据

```bash
python scripts/generate_data_js.py --bank all
```

从统一后的 `questions.json` 生成各题库的 `math-bank/data.js`。

### 重新生成 viewer 页面

```bash
python scripts/generate_viewer.py --bank all
```

从 `templates/math-bank.html` 生成各题库的 `math-bank/index.html`。

### 质量检查

```bash
python scripts/quality_check.py --book 660题
python scripts/quality_check.py --book 880题
python scripts/quality_check.py --book 1000题
python scripts/quality_check.py --book 大学深埋
```

生成 `temp/quality_report.html`，可检测 KaTeX 错误、无 `$` 包裹、图片缺失、重复 ID 等。

## 数据规范

统一后的 `questions.json` 结构见 `schemas/question-v1.md`。主要字段：

- `uid`：全局唯一标识
- `id`：原始显示题号
- `type`：选择题 / 填空题 / 计算题 / 证明题
- `content`：题干（数学公式用 `$...$` 包裹）
- `options`：选择题选项
- `sub_questions`：子问题数组
- `page`：页码
- `chapter`：章节名
- `has_image`：是否含图
- `image_ref`：图片引用

## 新增题库流程

1. 在根目录新建 `新题库/` 文件夹
2. 放入 `questions.json`（符合 `schemas/question-v1.md`）
3. 放置 PDF 页面图到 `pdf_images/`（或裁剪图到 `math-bank/crops/`）
4. 运行：
   ```bash
   python scripts/generate_data_js.py --bank 新题库
   python scripts/generate_viewer.py --bank 新题库
   ```
5. 在 `index.html` 首页添加该书卡片

## 注意事项

- 不要删除 `temp/backups/` 下的备份，除非你确认不再需要
- PDF 文件和裁剪图体积较大，已加入 `.gitignore`
- 修改 `templates/math-bank.html` 后，记得运行 `generate_viewer.py` 同步到各题库
