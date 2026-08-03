#!/usr/bin/env python3
"""WE 后处理：we_output.json → world_state.json + world_events.json。"""

import argparse, json, os, sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))

    state = {
        "world_time": data.get("world_time", ""),
        "time_advanced_days": data.get("time_advanced_days", 0),
        "forces": data.get("forces", []),
        "undercurrents": data.get("undercurrents", []),
    }
    events = {
        "world_time": data.get("world_time", ""),
        "time_advanced_days": data.get("time_advanced_days", 0),
        "on_camera_events": data.get("on_camera_events", []),
        "off_camera_events": data.get("off_camera_events", []),
        "undercurrent_progress": data.get("undercurrent_progress", []),
        "power_shift": data.get("power_shift", ""),
    }

    os.makedirs("cache/we", exist_ok=True)
    json.dump(state, open("cache/we/world_state.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(events, open("cache/we/world_events.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[OK] world_state.json + world_events.json → cache/we/")


if __name__ == "__main__":
    main()
