"""归档近纲脚本——读取 near_term_outline.md，解析章节范围，存入归档目录。

归档规则：
- 从文件第一行标题提取章节范围（如"第016-030章"）
- 复制到 outline/near_term_archive/{range}.md
- 归档已存在则跳过（幂等）
- 文件不存在（上游 SKIP）则静默退出
"""

import os
import re
import shutil
import sys

WORKSPACE = os.environ.get("WORKSPACE_DIR", os.getcwd())
SOURCE = os.path.join(WORKSPACE, "outline", "near_term_outline.md")
ARCHIVE_DIR = os.path.join(WORKSPACE, "outline", "near_term_archive")


def main():
    if not os.path.exists(SOURCE):
        print("near_term_outline.md 不存在，上游可能 SKIP，跳过归档")
        return

    with open(SOURCE, "r", encoding="utf-8") as f:
        content = f.read(512)  # 只读开头解析标题

    # 匹配 "# 近期大纲（第{M}-{N}章）" 或 "# 近期大纲（第M章）"
    match = re.search(r"第(\d+)[-–—](\d+)章", content)
    if match:
        range_name = f"{int(match.group(1)):03d}-{int(match.group(2)):03d}"
    else:
        match_single = re.search(r"第(\d+)章", content)
        if match_single:
            range_name = f"{int(match_single.group(1)):03d}"
        else:
            print("无法解析章节范围，文件名使用 unknown")
            range_name = "unknown"

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    dest = os.path.join(ARCHIVE_DIR, f"{range_name}.md")

    if os.path.exists(dest):
        print(f"归档已存在: {range_name}.md，跳过")
        return

    shutil.copy2(SOURCE, dest)
    print(f"已归档: {range_name}.md")
    # 输出变量，供下游引用
    print(f"<WF_VAR>archive_path:outline/near_term_archive/{range_name}.md</WF_VAR>")


if __name__ == "__main__":
    main()
