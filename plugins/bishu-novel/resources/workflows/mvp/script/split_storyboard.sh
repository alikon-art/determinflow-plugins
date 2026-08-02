#!/usr/bin/env bash

# 用法:
# ./split_storyboard.sh story/001/storyboard.md

set -e

INPUT_FILE="$1"

if [ -z "$INPUT_FILE" ]; then
    echo "用法:"
    echo "./split_storyboard.sh story/001/storyboard.md"
    exit 1
fi

if [ ! -f "$INPUT_FILE" ]; then
    echo "文件不存在: $INPUT_FILE"
    exit 1
fi

BASE_DIR="$(dirname "$INPUT_FILE")"
OUTPUT_DIR="$BASE_DIR/split_output"

mkdir -p "$OUTPUT_DIR"

awk -v OUTPUT_DIR="$OUTPUT_DIR" '
BEGIN {
    scene_count = 0
    in_storyboard = 0
}

{
    lines[NR] = $0

    # 找到镜头编排开始
    if ($0 ~ /^## 镜头编排/) {
        storyboard_start = NR
        in_storyboard = 1
    }

    # 记录镜头标题
    if (in_storyboard && $0 ~ /^### 镜头[0-9]+/) {
        scene_count++
        scene_start[scene_count] = NR
    }
}

END {

    total_lines = NR

    if (scene_count == 0) {
        print "未找到镜头"
        exit 1
    }

    # 找镜头编排结束位置
    storyboard_end = total_lines

    for (i = storyboard_start + 1; i <= total_lines; i++) {

        if (lines[i] ~ /^## / && lines[i] !~ /^## 镜头编排/) {
            storyboard_end = i - 1
            break
        }
    }

    # 输出每个镜头文件
    for (s = 1; s <= scene_count; s++) {

        current_start = scene_start[s]

        if (s < scene_count) {
            current_end = scene_start[s + 1] - 1
        } else {
            current_end = storyboard_end
        }

        filename = sprintf("%s/scene_%02d.md", OUTPUT_DIR, s)

        # 清空文件
        print "" > filename

        ########################################
        # 前置内容
        ########################################

        for (i = 1; i < storyboard_start; i++) {
            print lines[i] >> filename
        }

        print "" >> filename
        print "---" >> filename
        print "" >> filename

        ########################################
        # 当前镜头
        ########################################

        print "## 镜头编排" >> filename
        print "" >> filename

        for (i = current_start; i <= current_end; i++) {
            print lines[i] >> filename
        }

        print "" >> filename
        print "---" >> filename
        print "" >> filename

        ########################################
        # 后置内容
        ########################################

        for (i = storyboard_end + 1; i <= total_lines; i++) {
            print lines[i] >> filename
        }

        print "生成: " filename
    }
}
' "$INPUT_FILE"

echo ""
echo "完成"
echo "输出目录: $OUTPUT_DIR"