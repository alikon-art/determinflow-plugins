#!/usr/bin/env python3
"""CM 后处理：cm_output.json → character_states.json + minor_characters.json。"""

import argparse, json, os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))
    states = data.get("character_states", [])
    minors = data.get("minor_characters", [])

    os.makedirs("cache/cm", exist_ok=True)
    json.dump(states, open("cache/cm/character_states.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(minors, open("cache/cm/minor_characters.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[OK] character_states.json ({len(states)}角色) + minor_characters.json ({len(minors)}角色) → cache/cm/")


if __name__ == "__main__":
    main()
