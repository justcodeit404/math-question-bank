# 考研数学题库

本地静态数学题库系统，支持题目浏览、搜索、练习、抽检和质检。

已收录：**2502 道题目** · **4 本题册** · **81 个章节**

## 在线预览

部署在 GitHub Pages（如已开启）：https://justcodeit404.github.io/math-question-bank

本地使用：双击 `启动题库.bat`。

## 功能

- 按章节、题型、特征筛选题目
- 搜索题干、公式、章节
- 练习模式 + 进度记录
- 题目详情页查看原图
- 自动质量检查（KaTeX 错误、图片缺失、重复 ID 等）
- 单题/多题人工抽检

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动本地服务器
python scripts/server.py

# 3. 浏览器打开 http://localhost:8123
```

Windows 用户也可以直接双击：

- `启动题库.bat` — 打开首页
- `启动抽检.bat` — 打开抽检页面

## 项目结构

```
.
├── index.html                      # 首页
├── stats.js                        # 首页统计数据源
├── 660题/                          # 《数学基础过关660题》
├── 880题/                          # 《李林880题》
├── 1000题/                         # 《张宇1000题》
├── 大学深埋/                        # 《大学深埋做题本》
│   └── math-bank/
│       ├── index.html              # 交互式题库 viewer
│       └── data.js                 # 题库数据（由脚本生成）
├── scripts/                        # 核心脚本
│   ├── normalize_schema.py         # 统一 questions.json schema
│   ├── generate_data_js.py         # 生成 math-bank/data.js
│   ├── generate_viewer.py          # 生成 math-bank/index.html
│   ├── quality_check.py            # 生成质量报告
│   ├── migrate_660_images.py       # 迁移 660 图片到题库目录
│   ├── detect_question_boxes_660.py# 检测 660 题号色块
│   ├── extract_660_minimax.py      # 用 MiniMax 视觉模型提取题目
│   ├── fix_quality_issues.py       # 批量修复数据质量问题
│   └── server.py                   # 本地 HTTP 服务器
├── templates/
│   └── math-bank.html              # 题库 viewer 模板
├── schemas/
│   └── question-v1.md              # 统一 JSON schema 说明
├── vendor/katex/                   # 本地 KaTeX（离线可用）
├── temp/                           # 临时文件、报告、备份
└── requirements.txt                # Python 依赖
```

## 核心脚本用法

### 统一数据格式

```bash
python scripts/normalize_schema.py
```

把四个 `questions.json` 转成统一格式，并补齐 `uid`、`question_count` 等字段。

### 生成 viewer 数据

```bash
python scripts/generate_data_js.py --bank all
```

从 `questions.json` 生成各题库的 `math-bank/data.js`，并自动更新缓存戳。

### 生成 viewer 页面

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

生成 `temp/reports/quality_report_*.html`，可检测：

- KaTeX 语法错误
- 未闭合 `$`
- Unicode 数学符号
- 图片文件缺失
- 重复 ID

## 新增题库流程

1. 在根目录新建题库文件夹，例如 `新题库/`
2. 准备 `新题库/questions.json`，格式见 `schemas/question-v1.md`
3. 如有原图，放入 `新题库/pdf_images/`；如有裁剪图，放入 `新题库/math-bank/images/`
4. 在 `scripts/generate_data_js.py` 的 `BANK_CONFIG` 里添加配置
5. 生成数据与页面：
   ```bash
   python scripts/generate_data_js.py --bank 新题库
   python scripts/generate_viewer.py --bank 新题库
   ```
6. 更新 `index.html` 首页中的书卡片
7. 更新 `stats.js`（由 `generate_data_js.py --bank all` 自动生成）

## 从 PDF 提取题目（以 660 为例）

```bash
# 1. PDF 转页面图
python scripts/pdf_to_images_660.py

# 2. 检测题号色块
python scripts/detect_question_boxes_660.py --subject math

# 3. 用 MiniMax-M3 视觉模型提取题目
set MINIMAX_API_KEY=你的key
python scripts/extract_660_minimax.py --subject math --build-questions
```

> 660 高数/线代共用同一套脚本，通过 `--subject math|linear` 区分。

## 数据规范

统一后的 `questions.json` 主要字段：

| 字段 | 说明 |
|---|---|
| `uid` | 全局唯一标识 |
| `id` | 原始显示题号 |
| `type` | 选择题 / 填空题 / 计算题 / 证明题 |
| `content` | 题干，数学公式用 `$...$` 包裹 |
| `options` | 选择题选项 `{A, B, C, D}` |
| `sub_questions` | 子问题数组 |
| `page` | PDF 页码 |
| `chapter` | 章节名 |
| `has_image` | 是否含图 |
| `image_ref` | 图片引用 `{cropped, page, note}` |

完整规范见 `schemas/question-v1.md`。

## 技术栈

- 前端：原生 HTML / CSS / JavaScript + KaTeX（本地 vendor，离线可用）
- 数据：JSON + 自研 Python 脚本流水线
- OCR / 视觉提取：MiniMax-M3
- 本地服务器：`python -m http.server`

## 贡献与备份

- 关键脚本写入 `questions.json` 前会先写临时文件再原子替换，降低数据损坏风险
- 数据修改会自动备份到 `temp/backups/`
- PDF 文件、原始页面图、裁剪图已加入 `.gitignore`，不进入 Git 仓库
- 提交前请运行 `quality_check.py` 确保 0 问题

## License

仅供个人学习使用。
