#!/usr/bin/env python3
"""Prompt-only MiniMax H3 text-to-video API runner.

The business input is one prompt.  The test profile fixes 2K output, 5 seconds,
and 16:9 so that the first cost result is comparable.  The script deliberately
requires ``--execute`` before it can submit a billable task.  ``--dry-run``
performs only local schema and payload checks.

Examples::

    python3 scripts/runninghub_h3_t2v.py --dry-run \
        --prompt "雨后的城市屋顶，一只橙色猫缓慢行走，电影感镜头"
    python3 scripts/runninghub_h3_t2v.py --execute \
        --prompt "雨后的城市屋顶，一只橙色猫缓慢行走，电影感镜头"
    python3 scripts/runninghub_h3_t2v.py --query 1234567890

The API key is read from RH_API_KEY or the local ignored config.json.  It is
never written to the run record or printed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Mapping


ENDPOINT = "minimax/hailuo-h3/text-to-video"
RESOLUTION = "2K"
DEFAULT_DURATION = "5"
DEFAULT_RATIO = "16:9"
DEFAULT_BASE_URL = "https://www.runninghub.cn/openapi/v2"
TERMINAL_STATUSES = {"SUCCESS", "FAILED", "CANCEL"}
NON_TERMINAL_STATUSES = {"CREATE", "QUEUED", "RUNNING"}
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}
REDACTED = "[REDACTED]"


class RHError(RuntimeError):
    """A deterministic or transport error from the RunningHub route."""


class RequestTransportError(RHError):
    """A request may have failed after reaching the remote service."""


class SubmissionUncertain(RHError):
    """The submit request may have reached the server; never retry it blindly."""


class PollTimeout(RHError):
    def __init__(self, task_id: str, message: str):
        super().__init__(message)
        self.task_id = task_id


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def redact(value: Any) -> Any:
    """Recursively remove likely credentials from errors and saved responses."""
    if isinstance(value, Mapping):
        return {
            str(k): REDACTED if re.search(r"(?:api[_ -]?key|authorization|token|secret|password)", str(k), re.I)
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)\b(?:bearer\s+)?(?:sk|rk|ak)-[A-Za-z0-9_-]{12,}\b", REDACTED, value)
        value = re.sub(r"(?i)(Rh-Comfy-Auth=)[^&\"\s]+", r"\1" + REDACTED, value)
        return value
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RHError(f"读取 JSON 失败: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RHError(f"JSON 顶层必须是对象: {path}")
    return value


def get_config(config_path: Path) -> tuple[str, str]:
    config: dict[str, Any] = {}
    if config_path.is_file():
        config = load_json(config_path)
    api_key = os.environ.get("RH_API_KEY", "").strip() or str(config.get("apiKey", "")).strip()
    base_url = os.environ.get("RH_API_BASE_URL", "").strip() or str(
        config.get("baseUrl", DEFAULT_BASE_URL)
    ).strip()
    if not api_key:
        raise RHError("缺少 API Key：请设置 RH_API_KEY 或在本地 config.json 配置 apiKey")
    return api_key, base_url.rstrip("/")


def option_values(param: Mapping[str, Any]) -> list[str]:
    values = []
    for item in param.get("options") or []:
        if isinstance(item, Mapping):
            if item.get("value") is not None:
                values.append(str(item["value"]))
        else:
            values.append(str(item))
    return values


def load_h3_model(registry_path: Path) -> dict[str, Any]:
    registry = load_json(registry_path)
    for model in registry.get("models") or []:
        if isinstance(model, Mapping) and model.get("endpoint") == ENDPOINT:
            model = dict(model)
            params = {p.get("fieldKey"): p for p in model.get("params") or [] if isinstance(p, Mapping)}
            required = {"prompt", "resolution", "duration"}
            if not required.issubset(params):
                raise RHError(f"注册表中的 H3 schema 缺少字段: {sorted(required - set(params))}")
            if RESOLUTION not in option_values(params["resolution"]):
                raise RHError("注册表不再声明 MiniMax H3 的 2K 选项，停止提交")
            if DEFAULT_DURATION not in option_values(params["duration"]):
                raise RHError("注册表不再声明 MiniMax H3 的 5 秒选项，停止提交")
            if DEFAULT_RATIO not in option_values(params.get("ratio", {})):
                raise RHError("注册表不再声明 MiniMax H3 的 16:9 选项，停止提交")
            model["_params_by_key"] = params
            return model
    raise RHError(f"注册表找不到端点: {ENDPOINT}")


def build_payload(model: Mapping[str, Any], prompt: str, duration: str = DEFAULT_DURATION,
                  ratio: str = DEFAULT_RATIO) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise RHError("prompt 不能为空")
    params = model["_params_by_key"]
    if duration not in option_values(params["duration"]):
        raise RHError(f"duration={duration} 不在注册表选项中")
    if ratio not in option_values(params["ratio"]):
        raise RHError(f"ratio={ratio} 不在注册表选项中")
    return {"prompt": prompt, "resolution": RESOLUTION, "duration": duration, "ratio": ratio}


def request_json(url: str, api_key: str, payload: Mapping[str, Any], *, timeout: int,
                retries: int = 1, retry_transient: bool = False) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last: Exception | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(min(2 ** attempt, 15))
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            value = json.loads(raw) if raw else {}
            if not isinstance(value, dict):
                raise RHError(f"接口返回不是 JSON 对象: {url}")
            return value
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")[:800]
            last = RHError(f"HTTP {exc.code}: {redact(text)}")
            if exc.code in TRANSIENT_HTTP:
                if retry_transient and attempt + 1 < retries:
                    continue
                raise RequestTransportError(str(last)) from exc
            else:
                raise last from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if retry_transient and attempt + 1 < retries:
                continue
            raise RequestTransportError(f"请求失败: {type(exc).__name__}: {exc}") from exc
    raise RequestTransportError(f"请求失败: {last}")


def preview_price(base_url: str, api_key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Read the platform estimate before creating a billable task."""
    return request_json(
        f"{base_url}/price-preview/{ENDPOINT}", api_key, payload,
        timeout=60, retries=2, retry_transient=True,
    )


def submit(base_url: str, api_key: str, payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Submit once; an ambiguous transport failure must not be retried."""
    try:
        response = request_json(
            f"{base_url}/{ENDPOINT}", api_key, payload, timeout=90,
            retries=1, retry_transient=False,
        )
    except RequestTransportError as exc:
        raise SubmissionUncertain(f"提交结果不确定，未自动重试：{exc}") from exc
    error_code = response.get("errorCode") or response.get("error_code")
    error_message = response.get("errorMessage") or response.get("error_message")
    task_id = response.get("taskId") or response.get("task_id")
    if error_code or error_message:
        raise RHError(f"提交被平台拒绝: {error_code or ''} {error_message or ''}".strip())
    if not task_id:
        raise SubmissionUncertain("提交响应没有 taskId，不能判断是否已创建任务")
    return str(task_id), response


def query(base_url: str, api_key: str, task_id: str) -> dict[str, Any]:
    return request_json(
        f"{base_url}/query", api_key, {"taskId": task_id}, timeout=60,
        retries=3, retry_transient=True,
    )


def poll(base_url: str, api_key: str, task_id: str, interval: float, timeout: int,
         transitions: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.monotonic()
    last = None
    while time.monotonic() - started <= timeout:
        response = query(base_url, api_key, task_id)
        status = str(response.get("status") or "").upper()
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


def result_urls(response: Mapping[str, Any]) -> list[tuple[str, str]]:
    outputs = []
    for item in response.get("results") or []:
        if not isinstance(item, Mapping):
            continue
        url = item.get("url") or item.get("outputUrl")
        if url:
            output_type = str(item.get("outputType") or "mp4").lower()
            outputs.append((str(url), output_type))
    return outputs


def download(url: str, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-H3-T2V/1"})
    with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as stream:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
            total += len(chunk)
    return total


def media_probe(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return {"error": f"ffprobe failed: {type(exc).__name__}: {exc}"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def recursive_values(value: Any, names: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in names:
                found.append(item)
            found.extend(recursive_values(item, names))
    elif isinstance(value, list):
        for item in value:
            found.extend(recursive_values(item, names))
    return found


def billing_fields(preview: Mapping[str, Any] | None, final: Mapping[str, Any] | None) -> dict[str, Any]:
    preview = preview or {}
    final = final or {}
    estimated = preview.get("estimatedPrice")
    currency = preview.get("currency")
    actual_names = {"consumecoins", "consumemoney", "taskcosttime", "actualprice", "cost", "price"}
    actual = recursive_values(final, actual_names)
    return {
        "estimate": estimated,
        "estimate_currency": currency,
        "estimate_source": "price-preview" if estimated is not None else None,
        "actual_observed": actual[0] if actual else None,
        "actual_source": "final_query_response" if actual else None,
        "settlement_status": "observed" if actual else "unknown_pending_account_bill",
    }


def output_media_info(probe: Mapping[str, Any]) -> dict[str, Any]:
    streams = [s for s in probe.get("streams", []) if isinstance(s, Mapping)]
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = probe.get("format", {}).get("duration")
    return {
        "duration_seconds": float(duration) if duration is not None else None,
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "has_audio": bool(audio),
        "raw_probe": probe,
    }


def write_record(run_dir: Path, record: Mapping[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(redact(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


CSV_FIELDS = [
    "run_id", "task_id", "endpoint", "resolution", "duration_requested", "ratio",
    "status", "submitted_at", "completed_at", "elapsed_seconds", "estimate",
    "estimate_currency", "actual_observed", "actual_source", "settlement_status",
    "output_path", "output_duration_seconds", "width", "height", "has_audio", "error",
]


def append_cost_csv(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({key: redact(row.get(key)) for key in CSV_FIELDS})


def cost_row(record: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    outputs = record.get("outputs") or []
    first = outputs[0] if outputs else {}
    media = first.get("media") or {}
    return {
        "run_id": record.get("run_id"), "task_id": record.get("task_id"),
        "endpoint": ENDPOINT, "resolution": RESOLUTION,
        "duration_requested": args.duration, "ratio": args.ratio,
        "status": record.get("status"), "submitted_at": record.get("submitted_at"),
        "completed_at": record.get("completed_at"), "elapsed_seconds": record.get("elapsed_seconds"),
        **(record.get("cost") or {}), "output_path": first.get("local_path"),
        "output_duration_seconds": media.get("duration_seconds"),
        "width": media.get("width"), "height": media.get("height"),
        "has_audio": media.get("has_audio"), "error": record.get("error", ""),
    }


def prompt_from_args(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return (args.prompt or "").strip()


def default_paths() -> tuple[Path, Path, Path]:
    root = Path(__file__).resolve().parents[1]
    return (
        root / "output/runninghub/api/config.json",
        root / "output/runninghub/api/developer-kit/model-registry.public.json",
        root / "output/runninghub/api/h3_t2v_runs",
    )


def make_parser() -> argparse.ArgumentParser:
    config, registry, output = default_paths()
    parser = argparse.ArgumentParser(description="MiniMax H3 prompt-only 2K T2V API test")
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--query", metavar="TASK_ID", help="只查询已有任务，不创建新任务")
    parser.add_argument("--dry-run", action="store_true", help="只做本地 schema/payload 检查")
    parser.add_argument("--execute", action="store_true", help="允许提交一条付费任务")
    parser.add_argument("--config", type=Path, default=config)
    parser.add_argument("--registry", type=Path, default=registry)
    parser.add_argument("--output-dir", type=Path, default=output)
    parser.add_argument("--duration", default=DEFAULT_DURATION)
    parser.add_argument("--ratio", default=DEFAULT_RATIO)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=int, default=1800)
    return parser


def run_dry(model: Mapping[str, Any], prompt: str, duration: str, ratio: str) -> int:
    payload = build_payload(model, prompt, duration, ratio)
    print(json.dumps({
        "endpoint": ENDPOINT,
        "payload": payload,
        "billing": "not_requested",
        "generation": "not_submitted",
    }, ensure_ascii=False, indent=2))
    return 0


def run_query(args: argparse.Namespace) -> int:
    api_key, base_url = get_config(args.config)
    response = query(base_url, api_key, args.query)
    safe = redact(response)
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 0 if str(response.get("status", "")).upper() in TERMINAL_STATUSES else 2


def run_execute(args: argparse.Namespace, model: Mapping[str, Any], prompt: str) -> int:
    api_key, base_url = get_config(args.config)
    payload = build_payload(model, prompt, args.duration, args.ratio)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = args.output_dir / run_id
    started_at = now_utc()
    record: dict[str, Any] = {
        "run_id": run_id,
        "endpoint": ENDPOINT,
        "payload": payload,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "started_at": iso(started_at),
        "status": "PREFLIGHT",
        "transitions": [],
        "price_preview": None,
        "submit_response": None,
        "final_response": None,
        "outputs": [],
        "cost": billing_fields(None, None),
    }
    write_record(run_dir, record)
    try:
        preview = preview_price(base_url, api_key, payload)
        record["price_preview"] = redact(preview)
        if preview.get("errorCode") or preview.get("errorMessage"):
            raise RHError(
                f"价格预估失败: {preview.get('errorCode', '')} {preview.get('errorMessage', '')}".strip()
            )
        record["status"] = "PRICE_PREVIEW_OK"
        write_record(run_dir, record)

        task_id, submit_response = submit(base_url, api_key, payload)
        record["task_id"] = task_id
        record["submit_response"] = redact(submit_response)
        record["submitted_at"] = iso(now_utc())
        record["status"] = "SUBMITTED"
        write_record(run_dir, record)

        final = poll(base_url, api_key, task_id, args.poll_interval, args.timeout, record["transitions"])
        completed_at = now_utc()
        record["final_response"] = redact(final)
        record["completed_at"] = iso(completed_at)
        record["status"] = str(final.get("status") or "UNKNOWN").upper()
        record["cost"] = billing_fields(preview, final)
        record["elapsed_seconds"] = (completed_at - started_at).total_seconds()
        if record["status"] != "SUCCESS":
            raise RHError(f"任务终态为 {record['status']}: {final.get('errorMessage', '')}".strip())

        for index, (url, output_type) in enumerate(result_urls(final)):
            suffix = ".mp4" if output_type in {"mp4", "video"} else "." + output_type
            destination = run_dir / f"output_{index:02d}{suffix}"
            size = download(url, destination)
            probe = media_probe(destination)
            info = output_media_info(probe) if "error" not in probe else probe
            record["outputs"].append({
                "url": url,
                "output_type": output_type,
                "local_path": str(destination),
                "size_bytes": size,
                "sha256": sha256(destination),
                "media": info,
            })
        if not record["outputs"]:
            raise RHError("任务 SUCCESS 但没有可下载的视频 URL")
        record["status"] = "MEDIA_VALIDATED"
        write_record(run_dir, record)
        first = record["outputs"][0]
        media = first.get("media", {})
        append_cost_csv(args.output_dir / "costs.csv", cost_row(record, args))
        print(f"[success] taskId={task_id}")
        print(f"[record] {run_dir / 'run.json'}")
        print(f"[cost] {args.output_dir / 'costs.csv'}")
        return 0
    except PollTimeout as exc:
        record["status"] = "TIMEOUT"
        record["error"] = str(exc)
        record["task_id"] = exc.task_id
        record["elapsed_seconds"] = (now_utc() - started_at).total_seconds()
        write_record(run_dir, record)
        append_cost_csv(args.output_dir / "costs.csv", cost_row(record, args))
        print(f"[timeout] {exc}", file=sys.stderr)
        print(f"[record] {run_dir / 'run.json'}", file=sys.stderr)
        return 2
    except SubmissionUncertain as exc:
        record["status"] = "SUBMISSION_UNCERTAIN"
        record["error"] = str(exc)
        record["elapsed_seconds"] = (now_utc() - started_at).total_seconds()
        write_record(run_dir, record)
        append_cost_csv(args.output_dir / "costs.csv", cost_row(record, args))
        print(f"[blocked] {exc}", file=sys.stderr)
        print(f"[record] {run_dir / 'run.json'}", file=sys.stderr)
        return 3
    except Exception as exc:
        record["status"] = "FAILED"
        record["error"] = str(exc)
        record["elapsed_seconds"] = (now_utc() - started_at).total_seconds()
        write_record(run_dir, record)
        append_cost_csv(args.output_dir / "costs.csv", cost_row(record, args))
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
    model = load_h3_model(args.registry)
    if args.dry_run:
        return run_dry(model, prompt, args.duration, args.ratio)
    return run_execute(args, model, prompt)


if __name__ == "__main__":
    raise SystemExit(main())
