---
name: json-to-md
description: 通用 JSON→Markdown 渲染脚本。支持两种模式：tree（目录下 JSON 递归渲染）和 character（角色骨架+信念+深层维度合并渲染）。用于建书管线的最终文档生成。
author: system
version: 1.0.0
---

## 用法

### tree 模式
递归读取目录下所有 JSON 文件，按文件名排序，每个 JSON 渲染为一个 ## section：
```
python json_to_md.py --mode tree --input-dir {book_dir}/world --output {book_dir}/meta/world_foundation.md --title "世界观基础"
```

### character 模式
读取角色缓存目录下的 skeleton.json + beliefs.json + *_deep.json，合并渲染为角色设定文档：
```
python json_to_md.py --mode character --book-dir {book_dir} --output {book_dir}/meta/character_profiles.md
```

### 通用参数
- `--mode`: tree | character
- `--input-dir`: JSON 文件目录（tree 模式）
- `--book-dir`: 书籍根目录（character 模式，自动找 cache/character/ 子目录）
- `--output`: 输出 Markdown 文件路径
- `--title`: 一级标题（默认 "文档"）
