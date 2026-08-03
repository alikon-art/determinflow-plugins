#!/usr/bin/env python3
"""SI 后处理：chapter.json → body.json。"""

import argparse, json, os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))

    os.makedirs("cache/si", exist_ok=True)
    json.dump(data, open("cache/si/body.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[OK] body.json → cache/si/")


if __name__ == "__main__":
    main()
