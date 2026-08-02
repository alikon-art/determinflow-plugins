#!/usr/bin/env python3
"""润色后处理：PP body.json → chapter.md"""

import argparse, json, os


def main():
    parser = argparse.ArgumentParser(description="PP JSON → chapter.md")
    parser.add_argument("--body-json", required=True, help="PP 产出的 body.json")
    parser.add_argument("--output", required=True, help="输出 chapter.md 路径")
    args = parser.parse_args()

    with open(args.body_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    body = data.get("body", "") if isinstance(data, dict) else str(data)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(body)

    print(f"[OK] {args.body_json} → {args.output} ({len(body)} chars)")


if __name__ == "__main__":
    main()
