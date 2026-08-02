#!/usr/bin/env python3
"""快照：保存 chapter.md 到 polish_history 目录。轮数自动递增。"""
import shutil, os, sys, re

chapter_num = sys.argv[1]
prefix = sys.argv[2]  # "pl" or "pp"

src = f"story/{chapter_num}/chapter.md"
dst_dir = f"story/{chapter_num}/polish_history"
os.makedirs(dst_dir, exist_ok=True)

# 自动判断轮数：取已有 round_N_pre_*.md 中最大 N + 1
max_round = 0
if os.path.exists(dst_dir):
    for f in os.listdir(dst_dir):
        m = re.match(r"round_(\d+)_pre_", f)
        if m:
            max_round = max(max_round, int(m.group(1)))
round_num = max_round + 1

dst = f"{dst_dir}/round_{round_num}_pre_{prefix}.md"

if not os.path.exists(src):
    print(f"ERROR: 源文件不存在: {src}")
    sys.exit(1)

shutil.copy2(src, dst)

with open(src) as f:
    content = f.read()
    length = len(content)

print(f"<WF_VAR>chapter_length:{length}</WF_VAR>")
print(f"<script_out>快照: {dst}（{length}字符）</script_out>")
