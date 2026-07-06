# 题库统一 JSON Schema v1.0

所有题库的 `questions.json` 统一按此格式存储，便于通用脚本、抽检、检测器复用同一套逻辑。

## 顶层结构

```json
{
  "schema_version": "1.0",
  "bank": "660",
  "title": "数学基础过关660题·数二",
  "total_pages": 149,
  "content_pages": 149,
  "total_questions": 660,
  "chapters": [
    {
      "name": "第一章 函数·极限·连续",
      "question_count": 251,
      "questions": [ /* ... */ ]
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | string | 是 | 当前为 `"1.0"` |
| `bank` | string | 是 | 题库标识：`"660"`、`"880"`、`"1000"`、`"大学深埋"` |
| `title` | string | 是 | 书名/题库标题 |
| `total_pages` | int \| null | 是 | PDF 总页数 |
| `content_pages` | int \| null | 是 | 实际内容页数，无则填 null |
| `total_questions` | int \| null | 是 | 总题目数 |
| `chapters` | array | 是 | 章节列表 |

## 章节结构

```json
{
  "name": "第一章 函数·极限·连续",
  "question_count": 251,
  "questions": [ /* ... */ ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 章节名 |
| `question_count` | int | 该章题目数（与 `questions.length` 一致） |
| `questions` | array | 题目数组 |

## 题目结构

```json
{
  "uid": "660-1",
  "id": "1",
  "qnum": 1,
  "type": "填空题",
  "content": "...",
  "options": null,
  "sub_questions": null,
  "page": 16,
  "printed_page": 1,
  "chapter": "第一章 函数·极限·连续",
  "section": null,
  "has_image": true,
  "image_ref": {
    "page": 16,
    "cropped": "../../temp/660_crops_v2/page_016_q1.png",
    "note": "自动裁剪的题目区域（660题合并版）",
    "original_page": null
  },
  "source": "数学基础过关660题·数二"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | string | **全局唯一**标识，用于排序、去重、跨题库定位 |
| `id` | string \| int | 原始显示题号，如 `1`、`"例1"` |
| `qnum` | int \| null | 可解析为数字的题号，无则 null |
| `type` | string | 选择题 / 填空题 / 计算题 / 证明题 |
| `content` | string | 题干，数学公式用 `$...$` 包裹 |
| `options` | object \| null | 选择题选项，如 `{"A":"...", "B":"..."}` |
| `sub_questions` | string[] \| null | 子问题列表 |
| `page` | int | 题目所在 PDF 页码 |
| `printed_page` | int \| null | 印刷页码（仅 660 有） |
| `chapter` | string | 章节名 |
| `section` | string \| null | 小节/分类，如 `"基础题"`（仅 880 有） |
| `has_image` | bool | 是否含图 |
| `image_ref` | object \| null | 图片引用 |
| `source` | string | 来源书名 |

### image_ref 结构

```json
{
  "page": 16,
  "cropped": "../../temp/660_crops_v2/page_016_q1.png",
  "note": "...",
  "original_page": null
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `page` | int | 图片所在页码 |
| `cropped` | string \| null | 裁剪图相对 viewer 的路径 |
| `note` | string \| null | 图片说明 |
| `original_page` | int \| null | 原书页码（仅大学深埋有） |

## UID 生成规则

确保跨题库、跨章节不重复：

- **660**: `660-{qnum}`（题号全局唯一）
- **880**: `880-{qnum}`（题号全局唯一）
- **1000**: `1000-{chapter}-{qnum}`（各章题号从 1 开始，需加章节区分）
- **大学深埋**: `大学深埋-{chapter}-{id}-p{page}`（id 多为"例1/例2"，需加页码区分）
