#!/usr/bin/env python3
"""CLI：不启 HTTP 服务时直接跑一个能力任务并等结果。

用法：
  python3 cli.py --config <config.json> run <capability> --input '{"prompt": "...", "image": "a.png"}' \
      --param ratio=9:16 --param duration=5
  python3 cli.py --config <config.json> query cap-xxxx
  python3 cli.py --config <config.json> list
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import CapabilityError  # noqa: E402
from service import CapabilityService  # noqa: E402


def parse_kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        try:
            v = json.loads(v)
        except ValueError:
            pass
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--manifests", default=str(Path(__file__).parent / "manifests"))
    ap.add_argument("--db", default=None)
    ap.add_argument("--artifacts", default=None)
    ap.add_argument("--repo-root", default=str(Path(__file__).parent.parent.parent))
    ap.add_argument("--timeout", type=int, default=1800)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("capability")
    p_run.add_argument("--input", default="{}", help="JSON 对象（媒体可传本地路径/URL/api文件名）")
    p_run.add_argument("--param", action="append", default=[], help="key=value，可多次")
    sub.add_parser("query").add_argument("task_id")
    sub.add_parser("list")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    default_dir = Path(args.config).parent
    db = Path(args.db or (default_dir / "capability_tasks.db"))
    artifacts = Path(args.artifacts or (default_dir / "artifacts"))
    svc = CapabilityService(config, Path(args.manifests), db, artifacts, Path(args.repo_root).resolve())

    if args.cmd == "list":
        print(json.dumps(svc.list_capabilities(), ensure_ascii=False, indent=1))
    elif args.cmd == "query":
        t = svc.get_task(args.task_id)
        print(json.dumps(t, ensure_ascii=False, indent=1) if t else "task not found")
        sys.exit(0 if t and t["task_status"] in ("SUCCEEDED", "FAILED") else 2)
    elif args.cmd == "run":
        request = {"input": json.loads(args.input), "parameters": parse_kv(args.param)}
        try:
            created = svc.create_task(args.capability, request)
        except CapabilityError as e:
            print(f"create failed: [{e.code}] {e}")
            sys.exit(1)
        print(f"task_id={created['task_id']} upstream={created.get('upstream_task_id')}", flush=True)
        deadline = time.time() + args.timeout
        last = None
        while time.time() < deadline:
            t = svc.get_task(created["task_id"])
            if t["task_status"] != last:
                print(f"[{time.strftime('%H:%M:%S')}] {t['task_status']}", flush=True)
                last = t["task_status"]
            if t["task_status"] in ("SUCCEEDED", "FAILED"):
                print(json.dumps(t, ensure_ascii=False, indent=1))
                sys.exit(0 if t["task_status"] == "SUCCEEDED" else 1)
            svc.poll_once()
            time.sleep(5)
        print("timeout")
        sys.exit(2)


if __name__ == "__main__":
    main()
