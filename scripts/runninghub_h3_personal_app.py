#!/usr/bin/env python3
"""Personal-key MiniMax H3 text-to-video test through a RunningHub AI App.

The standard-model endpoint requires an Enterprise-Shared key.  This runner
uses the personal-key-compatible AI App route instead.  The business input is
one prompt; the internal test profile fixes 2K as 2560x1440 and duration as
5 seconds.

The runner submits at most one task per invocation and records both the V2
query response and the legacy cost response when the latter is available.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runninghub_h3_t2v import (  # noqa: E402
    NON_TERMINAL_STATUSES,
    TERMINAL_STATUSES,
    RHError,
    PollTimeout,
    RequestTransportError,
    download,
    get_config,
    iso,
    media_probe,
    now_utc,
    output_media_info,
    redact,
    request_json,
    sha256,
    write_record,
)


APP_ID = "2084613917401243650"
APP_NAME = "minimax-h3-文生视频"
APP_RUN_PATH = "/task/openapi/ai-app/run"
RESOLUTION = "2K"
WIDTH = 2560
HEIGHT = 1440
DEFAULT_DURATION = "5"
DEFAULT_BASE_URL = "https://www.runninghub.cn/openapi/v2"

NODE_INFO = {
    "prompt": ("18", "prompt", "prompt"),
    "duration": ("20", "value", "duration(s)"),
    "width": ("23", "custom_width", "custom_width"),
    "height": ("23", "custom_height", "custom_height"),
}


def build_node_info(prompt: str, duration: str = DEFAULT_DURATION) -> list[dict[str, str]]:
    prompt = prompt.strip()
    if not prompt:
        raise RHError("prompt 不能为空")
    if not duration.isdigit() or not 5 <= int(duration) <= 15:
        raise RHError("duration 必须是 5-15 秒")
    values = {
        "prompt": prompt,
        "duration": duration,
        "width": str(WIDTH),
        "height": str(HEIGHT),
    }
    return [
        {
            "nodeId": node_id,
            "fieldName": field,
            "fieldValue": values[key],
            "description": description,
        }
        for key, (node_id, field, description) in NODE_INFO.items()
    ]


def submit(base_origin: str, api_key: str, prompt: str, duration: str) -> tuple[str, dict[str, Any]]:
    body = {
        "webappId": APP_ID,
        "apiKey": api_key,
        "nodeInfoList": build_node_info(prompt, duration),
    }
    try:
        response = request_json(
            f"{base_origin}{APP_RUN_PATH}", api_key, body,
            timeout=90, retries=1, retry_transient=False,
        )
    except RequestTransportError as exc:
        raise RHError(f"提交结果不确定，未自动重试：{exc}") from exc
    if response.get("code") != 0:
        raise RHError(f"AI 应用提交失败: {response.get('code')} {response.get('msg')}")
    data = response.get("data") or {}
    task_id = data.get("taskId") or data.get("task_id")
    if not task_id:
        raise RHError("AI 应用提交响应没有 taskId")
    return str(task_id), response


def query(base_url: str, api_key: str, task_id: str) -> dict[str, Any]:
    return request_json(
        f"{base_url}/query", api_key, {"taskId": task_id},
        timeout=60, retries=3, retry_transient=True,
    )


def legacy_cost_query(base_origin: str, api_key: str, task_id: str) -> dict[str, Any]:
    """The documented older endpoint may expose taskCostTime/consumeCoins."""
    return request_json(
        f"{base_origin}/task/openapi/outputs", api_key,
        {"apiKey": api_key, "taskId": task_id},
        timeout=60, retries=2, retry_transient=True,
    )


def poll(base_url: str, api_key: str, task_id: str, interval: float, timeout: int,
         transitions: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.monotonic()
    last = None
    while time.monotonic() - started <= timeout:
        response = query(base_url, api_key, task_id)
        status = str(response.get("status") or response.get("taskStatus") or "").upper()
        if status != last:
            event = {"status": status or "UNKNOWN", "observed_at": iso(now_utc())}
            transitions.append(event)
            print(f"[{event['observed_at']}] status={event['status']}", flush=True)
            last = status
        if status in TERMINAL_STATUSES:
            return response
        if status not in NON_TERMINAL_STATUSES:
            raise RHError(f"未知任务状态: {status or '<empty>'} taskId={task_id}")
        time.sleep(interval)
    raise PollTimeout(task_id, f"轮询超时（{timeout}s），请保留 taskId 后续查询")


def extract_outputs(response: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if not response:
        return []
    values: list[dict[str, str]] = []
    results = response.get("results") or []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, Mapping):
                continue
            url = item.get("url") or item.get("outputUrl") or item.get("fileUrl")
            if url:
                values.append({"url": str(url), "output_type": str(item.get("outputType") or "mp4")})
    data = response.get("data") or []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, Mapping):
                continue
            url = item.get("fileUrl") or item.get("url") or item.get("outputUrl")
            if url:
                values.append({"url": str(url), "output_type": str(item.get("fileType") or "mp4")})
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if item["url"] not in seen:
            unique.append(item)
            seen.add(item["url"])
    return unique


def cost_from_legacy(response: Mapping[str, Any] | None) -> dict[str, Any]:
    items = response.get("data") if response else None
    if not isinstance(items, list):
        return {
            "task_cost_time": None,
            "consume_coins": None,
            "consume_money": None,
            "third_party_consume_money": None,
            "actual_source": None,
            "settlement_status": "unknown_pending_account_bill",
        }
    for item in items:
        if isinstance(item, Mapping) and any(
            item.get(key) is not None
            for key in ("taskCostTime", "consumeCoins", "consumeMoney", "thirdPartyConsumeMoney")
        ):
            return {
                "task_cost_time": item.get("taskCostTime"),
                "consume_coins": item.get("consumeCoins"),
                "consume_money": item.get("consumeMoney"),
                "third_party_consume_money": item.get("thirdPartyConsumeMoney"),
                "actual_source": "task/openapi/outputs",
                "settlement_status": "observed",
            }
    return {
        "task_cost_time": None,
        "consume_coins": None,
        "consume_money": None,
        "third_party_consume_money": None,
        "actual_source": None,
        "settlement_status": "unknown_pending_account_bill",
    }


CSV_FIELDS = [
    "run_id", "task_id", "app_id", "app_name", "resolution", "width", "height",
    "duration_requested", "status", "submitted_at", "completed_at", "elapsed_seconds",
    "task_cost_time", "consume_coins", "consume_money", "third_party_consume_money",
    "actual_source", "settlement_status",
    "output_path", "output_duration_seconds", "output_width", "output_height", "has_audio", "error",
]


def append_cost_csv(path: Path, record: Mapping[str, Any], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    output = (record.get("outputs") or [{}])[0]
    media = output.get("media") or {}
    cost = record.get("cost") or {}
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({
            "run_id": record.get("run_id"), "task_id": record.get("task_id"),
            "app_id": APP_ID, "app_name": APP_NAME, "resolution": RESOLUTION,
            "width": WIDTH, "height": HEIGHT, "duration_requested": args.duration,
            "status": record.get("status"), "submitted_at": record.get("submitted_at"),
            "completed_at": record.get("completed_at"), "elapsed_seconds": record.get("elapsed_seconds"),
            **cost, "output_path": output.get("local_path"),
            "output_duration_seconds": media.get("duration_seconds"),
            "output_width": media.get("width"), "output_height": media.get("height"),
            "has_audio": media.get("has_audio"), "error": record.get("error", ""),
        })


def default_paths() -> tuple[Path, Path, Path]:
    root = Path(__file__).resolve().parents[1]
    return (
        root / "output/runninghub/api/config.json",
        root / "output/runninghub/api/developer-kit/model-registry.public.json",
        root / "output/runninghub/api/h3_personal_app_runs",
    )


def make_parser() -> argparse.ArgumentParser:
    config, _registry, output = default_paths()
    parser = argparse.ArgumentParser(description="Personal-key MiniMax H3 2K AI App test")
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--query", metavar="TASK_ID", help="只查询任务，不创建新任务")
    parser.add_argument("--dry-run", action="store_true", help="只打印个人版 AI App 请求，不联网")
    parser.add_argument("--execute", action="store_true", help="提交一条付费任务")
    parser.add_argument("--config", type=Path, default=config)
    parser.add_argument("--output-dir", type=Path, default=output)
    parser.add_argument("--duration", default=DEFAULT_DURATION)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=int, default=1800)
    return parser


def prompt_from_args(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return (args.prompt or "").strip()


def run_dry(prompt: str, duration: str) -> int:
    print(json.dumps({
        "route": "personal-ai-app",
        "webappId": APP_ID,
        "webappName": APP_NAME,
        "nodeInfoList": build_node_info(prompt, duration),
        "resolution": {"label": RESOLUTION, "width": WIDTH, "height": HEIGHT},
        "generation": "not_submitted",
    }, ensure_ascii=False, indent=2))
    return 0


def run_query(args: argparse.Namespace) -> int:
    api_key, base_url = get_config(args.config)
    response = query(base_url, api_key, args.query)
    print(json.dumps(redact(response), ensure_ascii=False, indent=2))
    return 0 if str(response.get("status", "")).upper() in TERMINAL_STATUSES else 2


def run_execute(args: argparse.Namespace, prompt: str) -> int:
    api_key, base_url = get_config(args.config)
    base_origin = base_url[:-len("/openapi/v2")] if base_url.endswith("/openapi/v2") else base_url
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(
        f"{time.time_ns()}".encode()
    ).hexdigest()[:8]
    run_dir = args.output_dir / run_id
    started_at = now_utc()
    record: dict[str, Any] = {
        "run_id": run_id, "route": "personal-ai-app", "webapp_id": APP_ID,
        "webapp_name": APP_NAME, "resolution": {"label": RESOLUTION, "width": WIDTH, "height": HEIGHT},
        "duration_requested": args.duration, "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "started_at": iso(started_at), "status": "PREFLIGHT", "transitions": [],
        "submit_response": None, "final_response": None, "legacy_cost_response": None,
        "outputs": [], "cost": cost_from_legacy(None),
    }
    write_record(run_dir, record)
    try:
        task_id, submit_response = submit(base_origin, api_key, prompt, args.duration)
        record["task_id"] = task_id
        record["submit_response"] = redact(submit_response)
        record["submitted_at"] = iso(now_utc())
        record["status"] = "SUBMITTED"
        write_record(run_dir, record)

        final = poll(base_url, api_key, task_id, args.poll_interval, args.timeout, record["transitions"])
        completed_at = now_utc()
        record["final_response"] = redact(final)
        record["completed_at"] = iso(completed_at)
        record["status"] = str(final.get("status") or final.get("taskStatus") or "UNKNOWN").upper()
        record["elapsed_seconds"] = (completed_at - started_at).total_seconds()

        try:
            legacy = legacy_cost_query(base_origin, api_key, task_id)
            record["legacy_cost_response"] = redact(legacy)
            record["cost"] = cost_from_legacy(legacy)
        except Exception as exc:
            record["cost_query_error"] = str(exc)

        if record["status"] != "SUCCESS":
            raise RHError(f"任务终态为 {record['status']}: {final.get('errorMessage', '')}".strip())

        output_items = extract_outputs(final)
        if record.get("legacy_cost_response"):
            output_items.extend(extract_outputs(record["legacy_cost_response"]))
        deduped: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in output_items:
            if item["url"] not in seen:
                deduped.append(item)
                seen.add(item["url"])
        for index, item in enumerate(deduped):
            output_type = item["output_type"].lower()
            suffix = ".mp4" if output_type in {"mp4", "video"} else "." + output_type
            destination = run_dir / f"output_{index:02d}{suffix}"
            size = download(item["url"], destination)
            probe = media_probe(destination)
            media = output_media_info(probe) if "error" not in probe else probe
            record["outputs"].append({
                "url": item["url"], "output_type": output_type,
                "local_path": str(destination), "size_bytes": size,
                "sha256": sha256(destination), "media": media,
            })
        if not record["outputs"]:
            raise RHError("任务 SUCCESS 但没有可下载的视频 URL")
        record["status"] = "MEDIA_VALIDATED"
        write_record(run_dir, record)
        append_cost_csv(args.output_dir / "costs.csv", record, args)
        print(f"[success] taskId={task_id}")
        print(f"[record] {run_dir / 'run.json'}")
        print(f"[cost] {args.output_dir / 'costs.csv'}")
        return 0
    except PollTimeout as exc:
        record["status"] = "TIMEOUT"
        record["task_id"] = exc.task_id
        record["error"] = str(exc)
        record["elapsed_seconds"] = (now_utc() - started_at).total_seconds()
        write_record(run_dir, record)
        append_cost_csv(args.output_dir / "costs.csv", record, args)
        print(f"[timeout] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        record["status"] = "FAILED"
        record["error"] = str(exc)
        record["elapsed_seconds"] = (now_utc() - started_at).total_seconds()
        write_record(run_dir, record)
        append_cost_csv(args.output_dir / "costs.csv", record, args)
        print(f"[failed] {exc}", file=sys.stderr)
        print(f"[record] {run_dir / 'run.json'}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    modes = int(bool(args.dry_run)) + int(bool(args.execute)) + int(bool(args.query))
    if modes != 1:
        raise SystemExit("必须且只能选择一个模式：--dry-run、--execute 或 --query")
    if args.query:
        return run_query(args)
    prompt = prompt_from_args(args)
    if args.dry_run:
        return run_dry(prompt, args.duration)
    if not prompt:
        raise SystemExit("--execute 需要 --prompt 或 --prompt-file")
    return run_execute(args, prompt)


if __name__ == "__main__":
    raise SystemExit(main())
