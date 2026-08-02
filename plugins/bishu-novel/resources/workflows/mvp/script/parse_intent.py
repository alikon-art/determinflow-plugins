"""解析意图分发器的 JSON 输出，拆分为 od_intent 和 se_intent 两个运行时变量。"""
import json
import sys


def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else ""
    if not filepath:
        print("<WF_VAR>od_intent:（空）</WF_VAR>")
        print("<WF_VAR>se_intent:（空）</WF_VAR>")
        print("<script_out>意图分发完成（空）</script_out>")
        return
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    od = data.get("od_intent", "（空）")
    se = data.get("se_intent", "（空）")
    print(f"<WF_VAR>od_intent:{od}</WF_VAR>")
    print(f"<WF_VAR>se_intent:{se}</WF_VAR>")
    print("<script_out>意图分发完成</script_out>")


if __name__ == "__main__":
    main()
