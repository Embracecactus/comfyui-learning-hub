#!/usr/bin/env python3
"""RunningHub 最小可复用客户端(仅标准库,零依赖)。

设计:通用传输(鉴权/上传/预估/提交/轮询/取消/下载/费用)与模型参数完全分离。
模型端点与参数来自 docs/05-RunningHub-API/data/runninghub-api-registry.json,
不要把参数硬编码进客户端。

历史验证状态(2026-09-14;2026-09-21修复仅离线验证):
  - query / resume / outputs / app-params / 上传 / 工作流与 AI 应用提交:
    本仓库已用真实 Key 实测;
  - 标准模型 API 提交(含 price-preview):个人 Key 返回 1014,需企业级-共享
    API Key(https://www.runninghub.cn/enterprise-api/consumerApi 创建);
  - 本文件不含任何真实 Key。Key 只从环境变量 RH_API_KEY 读取。

付费闸门:run / run-ai-app / run-workflow 必须显式传 --execute 才会创建任务;
不带 --execute 时只做本地检查并打印执行计划(dry-run),不发任何请求。
account / query / resume / outputs / price / app-params 不创建任务,无需闸门。

任务恢复:提交成功立刻把 taskId 写入 --record-dir 下的 JSON;轮询超时、
下载失败都不会触发重新提交——用 resume <taskId> 续查/下载/归档费用。
提交结果不确定(网络中断且响应未知)时保存 uncertain 记录并退出,
绝不自动重试提交。

示例:
    export RH_API_KEY=...            # 必需
    export RH_API_BASE_URL=...       # 可选,默认 https://www.runninghub.cn/openapi/v2
    python3 rh_min_client.py price minimax/hailuo-h3/text-to-video \
        '{"prompt":"…","resolution":"768P","duration":"5","ratio":"16:9"}'
    python3 rh_min_client.py run minimax/hailuo-h3/text-to-video \
        '{"prompt":"…","resolution":"768P","duration":"5","ratio":"16:9"}' --execute
    python3 rh_min_client.py run minimax/hailuo-h3/image-to-video \
        '{"prompt":"…","resolution":"2K","duration":"5","firstFrameUrl":""}' \
        --local-files firstFrameUrl=./first.png --execute
    python3 rh_min_client.py run-ai-app 2083105376052006914 \
        '[{"nodeId":"1","fieldName":"prompt","fieldValue":"…"}]' --execute
    python3 rh_min_client.py run-workflow - --inline ./workflow-api.json \
        --set '115.aspect_ratio=9:16 (Portrait Widescreen)' --execute
    python3 rh_min_client.py account             # 只读账户状态
    python3 rh_min_client.py query <taskId>
    python3 rh_min_client.py resume <taskId>      # 续查/下载/归档费用,不重新提交
    python3 rh_min_client.py outputs <taskId>     # 旧接口:费用字段+节点级失败归因
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_BASE_URL = "https://www.runninghub.cn/openapi/v2"
NON_TERMINAL = {"CREATE", "CREATED", "QUEUED", "RUNNING"}
TERMINAL_OK = {"SUCCESS"}
TERMINAL_FAIL = {"FAILED", "CANCEL", "CANCELED", "CANCELLED"}
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}


class RHError(RuntimeError):
    """确定性业务错误或不可恢复的传输错误。"""


class RHTimeout(RHError):
    """本地轮询超时。本地超时≠平台任务失败或停止扣费;保留 taskId 事后 resume。"""

    def __init__(self, task_id: str, message: str | None = None):
        super().__init__(message or f"本地轮询超时;用 resume {task_id} 续查,勿重新提交")
        self.task_id = task_id


class SubmissionUncertain(RHError):
    """提交请求可能已到达服务端(网络中断/响应无法解析);绝不能自动重试。"""


class TransportError(RHError):
    """网络层失败(连接/超时/HTTP 错误码/非 JSON 响应),未获得业务结果。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(value: object, key: str = "") -> object:
    """Remove credentials recursively, including echoed API demos and error text."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if str(k).lower() in
                {"apikey", "api_key", "authorization", "cookie", "token", "access_token"}
                else redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        if key:
            value = value.replace(key, "[REDACTED]")
        value = re.sub(r"(?i)(api[_-]?key=)[^&\s]+", r"\1[REDACTED]", value)
        return value
    return value


def checked(body: dict) -> dict:
    """Validate both legacy code/data and flat v2 errors before reading fields."""
    if not isinstance(body, dict):
        raise TransportError("Unexpected JSON response type")
    ok = (None, "", 0, "0")
    if body.get("code") not in ok or body.get("errorCode") not in ok:
        raise RHError(f"平台拒绝: {body.get('code') or body.get('errorCode')} "
                      f"{body.get('msg') or body.get('errorMessage') or ''}")
    if body.get("errorMessage"):
        raise RHError(f"平台返回错误: {body['errorMessage']}")
    data = body.get("data")
    if isinstance(data, dict):
        checked(data)
    return body


def task_response(body: dict) -> dict:
    """Normalize only task responses, not arbitrary legacy data collections."""
    checked(body)
    if isinstance(body.get("data"), dict) and not body.get("status"):
        body = body["data"]
    return body


def _request(url: str, key: str, payload: dict | None = None,
             multipart: tuple[str, str] | None = None, timeout: int = 60,
             retries: int = 3) -> dict:
    """Bearer 鉴权 POST。重试策略:仅瞬态传输错误(网络/408/429/5xx)指数退避;
    业务拒绝(HTTP 200 内 errorCode、4xx 参数错、401/403)不重试并按类型抛出;
    非 JSON 的 2xx 响应按瞬态传输错误处理(可能是网关错误页)。"""
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if multipart:
                field, path = multipart
                boundary = uuid.uuid4().hex
                body = (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                    f'filename="{Path(path).name}"\r\n'
                    f'Content-Type: application/octet-stream\r\n\r\n'
                ).encode() + Path(path).read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
                headers = {"Authorization": f"Bearer {key}",
                           "Content-Type": f"multipart/form-data; boundary={boundary}"}
            else:
                body = json.dumps(payload or {}).encode()
                headers = {"Authorization": f"Bearer {key}",
                           "Content-Type": "application/json"}
            req = urllib.request.Request(url, data=body, method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode(errors="replace")
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise TransportError("JSON response must be an object")
                return redact(parsed, key)
            except json.JSONDecodeError:
                last = TransportError(f"non-JSON 2xx response: {redact(raw[:200], key)!r}")
                if attempt >= retries:
                    raise last
                continue
        except urllib.error.HTTPError as e:
            detail = str(redact(e.read().decode(errors="replace"), key))[:300]
            if e.code in TRANSIENT_HTTP and attempt < retries:
                last = TransportError(f"HTTP {e.code}: {detail}")
                time.sleep(2 ** attempt)
                continue
            raise TransportError(f"HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = TransportError(f"{type(e).__name__}: {redact(str(e), key)}")
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise last
    raise last or RHError("unreachable")


class RunningHubClient:
    """通用任务生命周期客户端。endpoint 与 payload 由调用方按注册表给出。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 poll_interval: float = 5.0, max_poll_seconds: int = 1800):
        self.key = (api_key or os.environ.get("RH_API_KEY", "")).strip()
        # Key 惰性校验:dry-run/本地检查不联网,不应被强制要求 Key
        self.base = (base_url or os.environ.get("RH_API_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        # /task/openapi 与 /api/webapp 走主域(无 /openapi/v2 前缀),跟随 base_url 站点
        self.origin = self.base[:-len("/openapi/v2")] if self.base.endswith("/openapi/v2") else self.base
        self.poll_interval = poll_interval
        self.max_poll_seconds = max_poll_seconds

    def _require_key(self):
        if not self.key:
            raise RHError("缺少 API Key:设置 RH_API_KEY 环境变量(dry-run 不需要)")

    # -- 标准模型 API(/openapi/v2) --------------------------------------
    def upload(self, path: str | Path) -> str:
        self._require_key()
        """本地媒体必须先上传;返回 data.download_url 填入 *Url 字段。"""
        body = _request(f"{self.base}/media/upload/binary", self.key,
                        multipart=("file", str(path)), timeout=300)
        if body.get("code") != 0:
            raise RHError(f"upload failed: {json.dumps(body, ensure_ascii=False)[:300]}")
        return body["data"]["download_url"]

    def account_status(self) -> dict:
        """Read-only balance/key status; lowercase body 'apikey' is intentional."""
        self._require_key()
        return checked(_request(f"{self.origin}/uc/openapi/accountStatus", self.key,
                                {"apikey": self.key}))

    def price_preview(self, endpoint: str, payload: dict) -> dict:
        """Read-only quote. Access refusal is an error, never a zero-price quote."""
        self._require_key()
        body = checked(_request(f"{self.base}/price-preview/{endpoint}", self.key, payload))
        quote = body["data"] if isinstance(body.get("data"), dict) else body
        try:
            amount = Decimal(str(quote.get("estimatedPrice")))
            if not amount.is_finite() or amount < 0 or not quote.get("currency"):
                raise ValueError("invalid quote")
        except (InvalidOperation, ValueError) as exc:
            raise RHError("预估响应缺少有效非负estimatedPrice/currency，不创建任务") from exc
        return quote

    def _submit_once(self, url: str, payload: dict) -> str:
        self._require_key()
        try:
            body = _request(url, self.key, payload, timeout=90, retries=1)
        except TransportError as exc:
            raise SubmissionUncertain(f"提交结果不确定,未自动重试:{exc}") from exc
        try:
            checked(body)  # deterministic business refusal remains RHError
        except TransportError as exc:
            raise SubmissionUncertain('无法解析提交响应;请先核对任务,勿重复提交') from exc
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        task_id = body.get("taskId") or body.get("task_id") or data.get("taskId")
        if not task_id:
            raise SubmissionUncertain("响应未包含taskId;请核对控制台,勿重复提交")
        return str(task_id)

    def submit(self, endpoint: str, payload: dict) -> str:
        return self._submit_once(f"{self.base}/{endpoint}", payload)

    def query(self, task_id: str) -> dict:
        self._require_key()
        body = task_response(_request(f"{self.base}/query", self.key, {"taskId": task_id}))
        if not body.get("status"):
            raise RHError("任务查询响应缺少status;请保留taskId后重查")
        return body

    def poll(self, task_id: str) -> dict:
        """轮询到终态。终态 FAILED/CANCEL 也返回(调用方记录 usage/failedReason);
        未知状态立即报错(不无限等待);超时抛 RHTimeout(携带 taskId)。"""
        deadline = time.monotonic() + self.max_poll_seconds
        last = None
        while time.monotonic() < deadline:
            body = self.query(task_id)
            status = str(body.get("status") or "").upper()
            if status != last:
                print(f"[{_now()[11:19]}] {task_id} -> {status or '?'}", flush=True)
                last = status
            if status in TERMINAL_OK or status in TERMINAL_FAIL:
                return body
            if status and status not in NON_TERMINAL:
                raise RHError(f"未知任务状态 {status!r} taskId={task_id};"
                              f"请到控制台核对后再 resume")
            time.sleep(self.poll_interval)
        raise RHTimeout(task_id, f"本地轮询超时({self.max_poll_seconds}s),"
                                 f"平台任务可能仍在运行;用 resume {task_id} 续查")

    def download(self, url: str, destination: Path) -> tuple[int, str]:
        """下载产物;返回 (字节数, sha256)。下载失败可重跑 resume,勿重新生成。"""
        destination.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "rh-min-client/1.2"})
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(req, timeout=300) as r, destination.open("wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        return total, digest.hexdigest()

    def result_urls(self, final: dict) -> list[str]:
        return [u for u in (i.get("url") or i.get("outputUrl") or i.get("fileUrl")
                            for i in final.get("results") or []) if u]

    @staticmethod
    def media_probe(path: Path) -> dict:
        """ffprobe 实测宽高/帧率/时长/音轨;ffprobe 不可用时记录错误，不标为媒体验收通过。"""
        cmd = ["ffprobe", "-v", "error", "-show_entries",
               "format=duration,size:stream=index,codec_type,codec_name,width,height,avg_frame_rate",
               "-of", "json", str(path)]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
            probe = json.loads(out)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            return {"error": f"ffprobe unavailable: {type(e).__name__}"}
        streams = [s for s in probe.get("streams", []) if isinstance(s, dict)]
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        return {"duration_seconds": probe.get("format", {}).get("duration"),
                "width": video.get("width"), "height": video.get("height"),
                "video_codec": video.get("codec_name"),
                "avg_frame_rate": video.get("avg_frame_rate"),
                "has_audio": bool(audio), "audio_codec": audio.get("codec_name")}

    def archive_outputs(self, final: dict, download_dir: Path) -> list[dict]:
        """下载全部产物并做校验/媒体检查;单文件失败记录后继续其余文件。"""
        results = []
        for i, url in enumerate(self.result_urls(final)):
            lower = url.lower().split("?")[0]
            suffix = next((e for e in (".mp4", ".png", ".jpg", ".webp", ".gif",
                                       ".mp3", ".wav", ".zip") if lower.endswith(e)), ".mp4")
            dest = download_dir / f"output_{i:02d}{suffix}"
            entry: dict = {"url": url, "local_path": str(dest)}
            try:
                size, sha = self.download(url, dest)
                entry.update({"size_bytes": size, "sha256": sha,
                              "media": self.media_probe(dest)})
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                entry["download_error"] = f"{type(e).__name__}: {e};用 resume 重试下载,勿重新生成"
            results.append(entry)
        return results

    # -- 共享生命周期 -----------------------------------------------------
    def _finish(self, record: dict, run_dir: Path) -> dict:
        """提交后的共享收尾:落盘 → 轮询 → 记录终态与费用 → 下载归档。
        超时/失败都保留 task_record.json;不会重新提交。"""
        record_path = run_dir / "task_record.json"

        def save():
            run_dir.mkdir(parents=True, exist_ok=True)
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")

        task_id = record["task_id"]
        try:
            final = self.poll(task_id)
        except RHTimeout as exc:
            record["status"] = "POLL_TIMEOUT"
            record["errors"].append(str(exc))
            save()
            print(f"[timeout] {exc}\n[record] {record_path}", file=sys.stderr)
            raise
        record["final"] = final
        record["status"] = str(final.get("status") or "UNKNOWN").upper()
        record["usage"] = final.get("usage")
        save()
        if record["status"] in TERMINAL_OK:
            record["outputs"] = self.archive_outputs(final, run_dir)
            record["status"] = ("MEDIA_VALIDATED" if record["outputs"]
                                and all("download_error" not in o and "error" not in o.get("media", {})
                                        for o in record["outputs"])
                                else "OUTPUT_INCOMPLETE")
            save()
        print(f"[done] status={record['status']} "
              f"usage={json.dumps(record['usage'], ensure_ascii=False)}")
        print(f"[record] {record_path}")
        return record

    @staticmethod
    def _new_run_dir(record_dir: Path, label: str) -> Path:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        run_dir = Path(record_dir or "output/runninghub/api/matrix_runs") / f"{run_id}-{label}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def run(self, endpoint: str, payload: dict, local_files: dict | None = None,
            execute: bool = False, record_dir: Path | None = None,
            allow_unpriced: bool = False, source_chain: dict | None = None) -> dict:
        """标准模型 API 完整生命周期(execute=False 为 dry-run,不发请求)。"""
        record: dict = {"route": "standard-model-api", "endpoint": endpoint,
                        "payload": dict(payload), "submitted_at": None,
                        "status": "DRY_RUN", "transitions": [], "final": None,
                        "outputs": [], "usage": None, "errors": []}
        if source_chain is not None:
            record["source_chain"] = dict(source_chain)
        payload = dict(payload)
        for field, path in (local_files or {}).items():
            if not execute:
                if not Path(path).exists():
                    raise RHError(f"--local-files {field}={path}: 文件不存在")
                continue
            payload[field] = self.upload(path)
            record.setdefault("uploads", []).append(
                {"field": field, "bytes": Path(path).stat().st_size})
        record["payload"] = payload
        if not execute:
            print(json.dumps({"dry_run": True, "endpoint": endpoint,
                              "payload": payload,
                              "note": "加 --execute 才会创建付费任务"},
                             ensure_ascii=False, indent=2))
            return record

        self._require_key()
        preview, preview_err = None, None
        try:
            preview = self.price_preview(endpoint, payload)
            if preview.get("estimatedPrice") is None or not preview.get("currency"):
                raise RHError("预估响应缺少estimatedPrice/currency")
        except (TransportError, RHError) as e:
            preview_err = str(e)
            if not allow_unpriced:
                raise RHError(f"未取得有效预估价,未创建任务:{e};明确接受未知费用才用--allow-unpriced") from e
        record["price_preview"] = {"response": preview, "error": preview_err}

        run_dir = self._new_run_dir(record_dir, endpoint.replace("/", "_"))
        record_path = run_dir / "task_record.json"

        def save():
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")

        try:
            task_id = self.submit(endpoint, payload)
        except SubmissionUncertain as exc:
            record["status"] = "SUBMISSION_UNCERTAIN"
            record["errors"].append(str(exc))
            save()
            print(f"[blocked] {exc}\n[record] {record_path}\n"
                  f"[next] 到控制台核对是否已建任务;确认没有再重试,有则用 resume",
                  file=sys.stderr)
            raise
        except RHError as exc:
            record["status"] = "SUBMIT_REJECTED"
            record["errors"].append(str(exc))
            save()
            raise
        record["task_id"] = task_id
        record["submitted_at"] = _now()
        record["status"] = "SUBMITTED"
        save()
        print(f"[submit] taskId={task_id}\n[record] {record_path}")
        return self._finish(record, run_dir)

    # -- 工作流 / AI 应用 API(/task/openapi,个人 Key 可用) --------------
    def workflow_create(self, workflow_id: str | None, node_info_list: list[dict] | None = None,
                        workflow_inline: dict | None = None,
                        webhook_url: str | None = None,
                        instance_type: str | None = None) -> str:
        self._require_key()
        """workflowId 与 workflow 直传二选一。直传时 workflowId 用占位 "1"
        (平台规则:直传工作流与 nodeInfoList 不互通,参数须烤入 JSON)。"""
        payload: dict = {"apiKey": self.key}
        if workflow_inline is not None:
            payload["workflowId"] = "1"
            payload["workflow"] = json.dumps(workflow_inline, ensure_ascii=False)
        else:
            payload["workflowId"] = str(workflow_id)
        payload["nodeInfoList"] = node_info_list or []
        if webhook_url:
            payload["webhookUrl"] = webhook_url
        if instance_type:
            payload["instanceType"] = instance_type
        return self._submit_once(f"{self.origin}/task/openapi/create", payload)

    def ai_app_run(self, webapp_id: str, node_info_list: list[dict]) -> str:
        self._require_key()
        payload = {"apiKey": self.key, "webappId": str(webapp_id),
                   "nodeInfoList": node_info_list}
        return self._submit_once(f"{self.origin}/task/openapi/ai-app/run", payload)

    def ai_app_node_info(self, webapp_id: str) -> dict:
        self._require_key()
        """GET apiCallDemo:应用节点参数 schema(免费,用于拼 nodeInfoList)。"""
        url = f"{self.origin}/api/webapp/apiCallDemo?" + urllib.parse.urlencode(
            {"apiKey": self.key, "webappId": webapp_id})
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return checked(redact(json.loads(r.read().decode()), self.key))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RHError(str(redact(str(exc), self.key))) from None

    def workflow_outputs(self, task_id: str) -> dict:
        self._require_key()
        """deprecated 但含成本字段(taskCostTime/consumeCoins/thirdParty)与
        节点级 failedReason;与 query 的 usage 属同一任务,对账时只计一次。"""
        return _request(f"{self.origin}/task/openapi/outputs", self.key,
                        {"apiKey": self.key, "taskId": task_id})

    def workflow_cancel(self, task_id: str) -> dict:
        self._require_key()
        return _request(f"{self.origin}/task/openapi/cancel", self.key,
                        {"apiKey": self.key, "taskId": task_id})

    @staticmethod
    def bake_inline_params(workflow: dict, settings: dict[str, object]) -> dict:
        """把参数烤入 API 格式工作流 JSON(直传模式下 nodeInfoList 不生效)。
        settings 键为 "nodeId.fieldName";值按 JSON 解析,失败则按字符串。
        同时移除工作流内 RHSettingsNode 的占位 API Key 由调用方自行决定。"""
        wf = json.loads(json.dumps(workflow))  # deep copy
        for key, value in settings.items():
            node_id, field = key.split(".", 1)
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except json.JSONDecodeError:
                pass
            hit = False
            for node in wf.get("nodes", []):
                if str(node.get("id")) == str(node_id):
                    inputs = node.setdefault("inputs", {})
                    if isinstance(inputs, dict):
                        inputs[field] = value
                        hit = True
                    else:  # API 格式的 inputs 也可能是 list[{"name":…}]
                        for item in inputs:
                            if isinstance(item, dict) and item.get("name") == field:
                                item["value"] = value
                                hit = True
                    break
            if not hit:
                raise RHError(f"bake 失败:工作流中没有节点 {node_id}(键 {key})")
        return wf

    def run_ai_app(self, webapp_id: str, node_info_list: list[dict],
                   execute: bool = False, record_dir: Path | None = None) -> dict:
        """AI 应用路线完整生命周期(execute=False 为 dry-run)。"""
        record: dict = {"route": "ai-app", "webapp_id": str(webapp_id),
                        "node_info_list": node_info_list, "submitted_at": None,
                        "status": "DRY_RUN", "transitions": [], "final": None,
                        "outputs": [], "usage": None, "errors": []}
        if not execute:
            print(json.dumps({"dry_run": True, "route": "ai-app",
                              "webapp_id": webapp_id,
                              "node_info_list": node_info_list,
                              "note": "加 --execute 才会创建付费任务"},
                             ensure_ascii=False, indent=2))
            return record
        run_dir = self._new_run_dir(record_dir, f"aiapp-{webapp_id}")
        record_path = run_dir / "task_record.json"

        def save():
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")

        try:
            task_id = self.ai_app_run(webapp_id, node_info_list)
        except (RHError, TransportError) as exc:
            record["status"] = ("SUBMISSION_UNCERTAIN" if isinstance(exc, (SubmissionUncertain, TransportError))
                                else "SUBMIT_REJECTED")
            record["errors"].append(str(exc))
            save()
            print(f"[rejected] {exc}\n[record] {record_path}", file=sys.stderr)
            raise
        record["task_id"] = task_id
        record["submitted_at"] = _now()
        record["status"] = "SUBMITTED"
        save()
        print(f"[submit] taskId={task_id}\n[record] {record_path}")
        return self._finish(record, run_dir)

    def run_workflow(self, workflow_id: str | None, node_info_list: list[dict] | None,
                     workflow_inline_path: str | None = None,
                     bake: dict[str, str] | None = None,
                     instance_type: str | None = None,
                     execute: bool = False, record_dir: Path | None = None) -> dict:
        """工作流路线完整生命周期。--inline 直传 API 格式 JSON(个人 Key 可用),
        --set nodeId.field=value 烤入参数;否则用平台保存的 workflowId。"""
        record: dict = {"route": "workflow-api",
                        "workflow_id": workflow_id,
                        "inline": bool(workflow_inline_path),
                        "node_info_list": node_info_list or [],
                        "bake": bake or {}, "instance_type": instance_type,
                        "submitted_at": None, "status": "DRY_RUN",
                        "transitions": [], "final": None, "outputs": [],
                        "usage": None, "errors": []}
        inline = None
        if workflow_inline_path:
            wf = json.loads(Path(workflow_inline_path).read_text(encoding="utf-8"))
            inline = self.bake_inline_params(wf, bake or {}) if bake else wf
            record["baked_workflow_sha256"] = hashlib.sha256(
                json.dumps(inline, sort_keys=True, ensure_ascii=False)
                .encode()).hexdigest()[:16]
        if not execute:
            print(json.dumps({"dry_run": True, "route": "workflow-api",
                              "inline": record["inline"], "bake": record["bake"],
                              "node_info_list": record["node_info_list"],
                              "note": "加 --execute 才会创建付费任务"},
                             ensure_ascii=False, indent=2))
            return record
        run_dir = self._new_run_dir(record_dir, f"wf-{workflow_id or 'inline'}")
        record_path = run_dir / "task_record.json"

        def save():
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")

        try:
            task_id = self.workflow_create(workflow_id, node_info_list,
                                           workflow_inline=inline,
                                           instance_type=instance_type)
        except (RHError, TransportError) as exc:
            record["status"] = ("SUBMISSION_UNCERTAIN" if isinstance(exc, (SubmissionUncertain, TransportError))
                                else "SUBMIT_REJECTED")
            record["errors"].append(str(exc))
            save()
            print(f"[rejected] {exc}\n[record] {record_path}", file=sys.stderr)
            raise
        record["task_id"] = task_id
        record["submitted_at"] = _now()
        record["status"] = "SUBMITTED"
        save()
        print(f"[submit] taskId={task_id}\n[record] {record_path}")
        return self._finish(record, run_dir)


# ---------------------------------------------------------------------------
# CLI。query/resume/outputs/price/app-params 不创建任务;
# run/run-ai-app/run-workflow 需要 --execute 才创建付费任务。
# ---------------------------------------------------------------------------
def build_record_from_existing(client: RunningHubClient, task_id: str,
                               download_dir: Path) -> dict:
    """resume 共用逻辑:查询既有任务到终态并归档,不创建任何新任务。"""
    final = client.query(task_id)
    status = str(final.get("status") or "").upper()
    if status in NON_TERMINAL or status == "":
        final = client.poll(task_id)
        status = str(final.get("status") or "").upper()
    record = {"route": "resume", "task_id": task_id, "status": status,
              "final": final, "usage": final.get("usage"),
              "outputs": [], "resumed_at": _now()}
    if status in TERMINAL_OK:
        record["outputs"] = client.archive_outputs(final, download_dir)
        if not record["outputs"] or any("download_error" in o or "error" in o.get("media", {}) for o in record["outputs"]):
            record["status"] = "OUTPUT_INCOMPLETE"
    return record


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--record-dir", type=Path,
                        default=Path("output/runninghub/api/matrix_runs"),
                        help="任务记录与产物保存目录")
    common.add_argument("--poll-interval", type=float, default=5.0)
    common.add_argument("--timeout", type=int, default=1800,
                        help="本地轮询上限秒数;超时不代表平台任务失败")

    ap = argparse.ArgumentParser(description="RunningHub 最小客户端(付费任务需 --execute)",
                                 parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    add("account", "只读账户状态(免费;不创建任务)")

    p = add("query", "查一次任务状态(免费)")
    p.add_argument("task_id")

    p = add("resume", "续查已有任务到终态并下载/归档(不重新提交)")
    p.add_argument("task_id")
    p.add_argument("--download-dir", type=Path, default=None)

    p = add("outputs", "旧接口:费用字段与节点级失败归因(免费)")
    p.add_argument("task_id")

    p = add("price", "价格预估,不创建任务(企业共享 Key 适用)")
    p.add_argument("endpoint")
    p.add_argument("payload", help="JSON 字符串")

    p = add("run", "标准模型 API 提交(需 --execute)")
    p.add_argument("endpoint")
    p.add_argument("payload", help="JSON 字符串")
    p.add_argument("--allow-unpriced", action="store_true", help="显式接受无法预估的费用")
    p.add_argument("--local-files", action="append", default=[],
                   metavar="FIELD=PATH", help="本地媒体字段,先上传再提交;可重复")
    p.add_argument("--execute", action="store_true", help="确认创建付费任务")

    p = add("run-ai-app", "AI 应用提交(需 --execute)")
    p.add_argument("webapp_id")
    p.add_argument("node_info_list", help="JSON 数组字符串")
    p.add_argument("--execute", action="store_true", help="确认创建付费任务")

    p = add("run-workflow", "工作流提交(需 --execute;workflowId 或 --inline 二选一)")
    p.add_argument("workflow_id", help="平台工作流 ID;'-' 表示用 --inline 直传")
    p.add_argument("--inline", dest="inline_path", help="API 格式工作流 JSON 路径")
    p.add_argument("--set", action="append", default=[], metavar="NODE.FIELD=VALUE",
                   help="烤入直传工作流的参数(值按 JSON 解析);可重复")
    p.add_argument("--node-info", dest="node_info", default="[]",
                   help="workflowId 模式的 nodeInfoList JSON 数组")
    p.add_argument("--instance-type", default=None, help="如 plus(48G 机器)")
    p.add_argument("--execute", action="store_true", help="确认创建付费任务")

    p = add("video", "H3单提示词入口；默认dry-run，显式选择Key通道")
    p.add_argument("--prompt", required=True)
    p.add_argument("--key-type", choices=("consumer-member", "enterprise-shared"), required=True)
    p.add_argument("--resolution", choices=("768P", "2K"), default="2K")
    p.add_argument("--duration", type=int, choices=range(5, 16), default=5)
    p.add_argument("--ratio", choices=("21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "9:21"), default="16:9")
    p.add_argument("--webapp-id", default="2083105376052006914")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--allow-unpriced", action="store_true")

    p = add("app-params", "查询 AI 应用节点参数 schema(免费)")
    p.add_argument("webapp_id")

    args = ap.parse_args(argv)
    client = RunningHubClient(poll_interval=args.poll_interval,
                              max_poll_seconds=args.timeout)

    if args.cmd == "video":
        if not args.prompt.strip():
            raise RHError("提示词不能为空")
        payload = {"prompt": args.prompt, "resolution": args.resolution,
                   "duration": str(args.duration), "ratio": args.ratio}
        if args.key_type == "enterprise-shared":
            record = client.run("minimax/hailuo-h3/text-to-video", payload,
                                execute=args.execute, record_dir=args.record_dir,
                                allow_unpriced=args.allow_unpriced)
        else:
            nodes = [{"nodeId": "1", "fieldName": k, "fieldValue": v,
                      "description": k} for k, v in payload.items()]
            record = client.run_ai_app(args.webapp_id, nodes, execute=args.execute,
                                      record_dir=args.record_dir)
        return 0 if record.get("status") in ("MEDIA_VALIDATED", "DRY_RUN") else 1
    if args.cmd == "account":
        print(json.dumps(redact(client.account_status(), client.key), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "query":
        final = client.query(args.task_id)
        print(json.dumps(final, ensure_ascii=False, indent=2))
        status = str(final.get("status") or "").upper()
        return 0 if status in TERMINAL_OK else (4 if status in TERMINAL_FAIL else 2)
    if args.cmd == "resume":
        dd = args.download_dir or (args.record_dir / f"resume-{args.task_id}")
        record = build_record_from_existing(client, args.task_id, dd)
        out = args.record_dir / f"resume-{args.task_id}" / "task_record.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(json.dumps({"status": record["status"], "usage": record["usage"],
                          "outputs": record["outputs"], "record": str(out)},
                         ensure_ascii=False, indent=2))
        return 0 if record["status"] in TERMINAL_OK else 4
    if args.cmd == "outputs":
        print(json.dumps(client.workflow_outputs(args.task_id),
                         ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "price":
        body = client.price_preview(args.endpoint, json.loads(args.payload))
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "app-params":
        print(json.dumps(client.ai_app_node_info(args.webapp_id),
                         ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "run":
        local_files = {}
        for item in args.local_files:
            if "=" not in item:
                raise SystemExit(f"--local-files 需要 FIELD=PATH 形式: {item}")
            field, path = item.split("=", 1)
            local_files[field] = path
        record = client.run(args.endpoint, json.loads(args.payload),
                            local_files=local_files, execute=args.execute,
                            record_dir=args.record_dir, allow_unpriced=args.allow_unpriced)
        return 0 if record.get("status") in ("MEDIA_VALIDATED", "DRY_RUN") else 1
    if args.cmd == "run-ai-app":
        record = client.run_ai_app(args.webapp_id, json.loads(args.node_info_list),
                                   execute=args.execute, record_dir=args.record_dir)
        return 0 if record.get("status") in ("MEDIA_VALIDATED", "DRY_RUN") else 1
    if args.cmd == "run-workflow":
        bake = {}
        for item in getattr(args, "set"):
            if "=" not in item:
                raise SystemExit(f"--set 需要 NODE.FIELD=VALUE 形式: {item}")
            key, value = item.split("=", 1)
            bake[key] = value
        inline = args.inline_path
        if args.workflow_id == "-" and not inline:
            raise SystemExit("workflow_id 为 '-' 时必须给 --inline")
        if args.workflow_id != "-" and inline:
            raise SystemExit("workflow_id 与 --inline 只能二选一")
        record = client.run_workflow(
            None if args.workflow_id == "-" else args.workflow_id,
            json.loads(args.node_info), workflow_inline_path=inline,
            bake=bake or None, instance_type=args.instance_type,
            execute=args.execute, record_dir=args.record_dir)
        return 0 if record.get("status") in ("MEDIA_VALIDATED", "DRY_RUN") else 1
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RHError, ValueError, OSError) as exc:
        print(str(redact(str(exc), os.environ.get("RH_API_KEY", ""))), file=sys.stderr)
        raise SystemExit(2)
