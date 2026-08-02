#!/usr/bin/env python3
"""意图分发器后处理：cache/intent.json → od_intent + se_intent 工作流变量"""

import argparse, json, sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="意图分发器输出的 JSON 文件路径")
    args = parser.parse_args()

    try:
        data = json.load(open(args.input, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        print("<WF_VAR>od_intent:（空）</WF_VAR>")
        print("<WF_VAR>se_intent:（空）</WF_VAR>")
        return

    od = data.get("od_intent", "（空）") or "（空）"
    se = data.get("se_intent", "（空）") or "（空）"

    print(f"<WF_VAR>od_intent:{od}</WF_VAR>")
    print(f"<WF_VAR>se_intent:{se}</WF_VAR>")


if __name__ == "__main__":
    main()
