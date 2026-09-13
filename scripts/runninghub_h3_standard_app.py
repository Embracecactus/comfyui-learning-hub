#!/usr/bin/env python3
"""Run one prompt-only 2K H3 workflow-backed AI App test.

This is a thin profile over the existing personal AI App runner.  The target
app is workflow-backed and exposes all four H3 inputs on node 1, unlike the
custom-node app used by the first 2K attempt.
"""

from __future__ import annotations

import sys

import runninghub_h3_personal_app as runner


runner.APP_ID = "2083105376052006914"
runner.APP_NAME = "Minimax H3 文生视频工作流"
runner.RESOLUTION = "2K"
runner.WIDTH = 2560
runner.HEIGHT = 1440
runner.DEFAULT_DURATION = "5"


def build_node_info(prompt: str, duration: str = "5") -> list[dict[str, str]]:
    prompt = prompt.strip()
    if not prompt:
        raise runner.RHError("prompt 不能为空")
    if not duration.isdigit() or not 5 <= int(duration) <= 15:
        raise runner.RHError("duration 必须是 5-15 秒")
    return [
        {"nodeId": "1", "fieldName": "prompt", "fieldValue": prompt, "description": "prompt"},
        {"nodeId": "1", "fieldName": "resolution", "fieldValue": "2K", "description": "resolution"},
        {"nodeId": "1", "fieldName": "duration", "fieldValue": duration, "description": "duration"},
        {"nodeId": "1", "fieldName": "ratio", "fieldValue": "16:9", "description": "ratio"},
    ]


runner.build_node_info = build_node_info


if __name__ == "__main__":
    raise SystemExit(runner.main(sys.argv[1:]))
