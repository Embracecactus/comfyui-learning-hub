"""通用 RunningHub 工作流能力单元引擎。

一个「能力单元」= 一份能力清单（manifest）+ 任意基础工作流（API 格式 JSON）。
新增工作流只需新增清单文件，不改引擎代码。

清单 schema（v1）：
{
  "capability": "h3-r2v-vertical",          // 能力名（API 调用时引用）
  "title": "H3 商品图+动作参考生视频",
  "output": "video",                        // image | video（仅用于结果标注）
  "workflowFile": "path/相对仓库根",         // 与 workflowInline 二选一
  "workflowInline": { ... },                // 直接内嵌 API 格式工作流
  "outputNodes": ["92"],                    // 采集哪些节点的产物
  "params": {
    "<语义参数名>": {
      "node": "138", "field": "value",      // 目标节点与字段
      "type": "string|number|boolean|enum|image|video|audio",
      "required": true,
      "default": ...,                        // 非必填的默认值
      "values": {"9:16": "9:16 (Portrait Widescreen)", ...}   // enum 专用：对外名→工作流枚举
    }
  }
}

请求体（POST /v1/tasks）：
{
  "capability": "h3-r2v-vertical",
  "input":  {"prompt": "...", "image": "<本地路径|http URL|api/fileName>", "video": "..."},
  "parameters": {"ratio": "9:16", "duration": 5}
}
"""

from __future__ import annotations

import copy
import json
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from rh_client import _post

RH_HOST = "https://www.runninghub.cn"
WORKFLOW_ID_PLACEHOLDER = "1"  # workflow 直传时的占位（服务端要求正数，实际被 workflow 覆盖）

# RunningHub code → 对外稳定错误枚举（doc14 §3.3）
ERROR_MAP = {
    301: "INVALID_ARGUMENT", 380: "WORKFLOW_NOT_FOUND", 412: "INVALID_ARGUMENT",
    415: "RATE_LIMITED", 416: "INSUFFICIENT_BALANCE", 421: "RATE_LIMITED",
    423: "TASK_NOT_FOUND", 433: "INVALID_ARGUMENT", 802: "AUTH_FAILED",
    803: "INVALID_ARGUMENT", 806: "AUTH_FAILED", 807: "TASK_NOT_FOUND",
    808: "MEDIA_REJECTED", 809: "MEDIA_REJECTED", 814: "RATE_LIMITED",
    1501: "CONTENT_REJECTED", 1505: "CONTENT_REJECTED", 1007: "INVALID_ARGUMENT",
}
MEDIA_TYPES = {"image", "video", "audio"}
SCALAR_TYPES = {"string", "number", "boolean", "enum"}


class CapabilityError(RuntimeError):
    def __init__(self, code: str, message: str, upstream: dict | None = None):
        super().__init__(message)
        self.code = code
        self.upstream = upstream or {}


def load_manifest(path: Path) -> dict:
    m = json.loads(path.read_text(encoding="utf-8"))
    for key in ("capability", "params", "outputNodes"):
        if key not in m:
            raise CapabilityError("INVALID_ARGUMENT", f"清单缺少 {key}: {path}")
    return m


def load_base_workflow(manifest: dict, repo_root: Path) -> dict:
    if manifest.get("workflowInline"):
        return copy.deepcopy(manifest["workflowInline"])
    wf_path = (repo_root / manifest["workflowFile"]).resolve()
    return json.loads(wf_path.read_text(encoding="utf-8"))


def resolve_media(api_key: str, value, work_dir: Path) -> str:
    """媒体值 → RunningHub fileName。支持：api/xxx（已上传）、本地路径、http(s) URL。"""
    if not isinstance(value, str) or not value:
        raise CapabilityError("INVALID_ARGUMENT", "媒体参数必须是非空字符串")
    if value.startswith("api/"):
        return value
    p = None
    if value.startswith("http://") or value.startswith("https://"):
        work_dir.mkdir(parents=True, exist_ok=True)
        p = work_dir / ("dl_" + uuid.uuid4().hex[:8] + "_" + Path(value.split("?")[0]).name)
        with urllib.request.urlopen(value, timeout=300) as r, p.open("wb") as f:
            f.write(r.read())
    else:
        p = Path(value)
        if not p.is_absolute():
            p = work_dir / p
        if not p.exists():
            raise CapabilityError("INVALID_ARGUMENT", f"本地媒体不存在: {value}")
    return upload_file(api_key, p)


def upload_file(api_key: str, path: Path, tries: int = 4) -> str:
    """POST /task/openapi/upload（504 常见，退避重试）。"""
    last = None
    for attempt in range(1, tries + 1):
        try:
            boundary = "----rhcap" + uuid.uuid4().hex
            body = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"apiKey\"\r\n\r\n{api_key}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"fileType\"\r\n\r\ninput\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                f"{RH_HOST}/task/openapi/upload", data=body, method="POST",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=300) as r:
                resp = json.loads(r.read().decode())
            if resp.get("code") != 0:
                raise CapabilityError("MEDIA_REJECTED", f"上传失败: {json.dumps(resp, ensure_ascii=False)[:300]}")
            return resp["data"]["fileName"]
        except CapabilityError:
            raise
        except Exception as e:
            last = e
            if attempt < tries:
                time.sleep(3 * attempt)
    raise CapabilityError("UPSTREAM_FAILED", f"上传失败: {last}")


def build_workflow(api_key: str, manifest: dict, base: dict,
                   request: dict, work_dir: Path) -> dict:
    """校验请求 → 深拷贝基础工作流 → 逐参数覆盖。任何清单外参数报 INVALID_ARGUMENT。"""
    wf = copy.deepcopy(base)
    params = manifest["params"]
    req_input = request.get("input") or {}
    req_params = request.get("parameters") or {}

    merged: dict[str, object] = {}
    for name, spec in params.items():
        raw = req_params.get(name, req_input.get(name, spec.get("default")))
        ptype = spec.get("type", "string")
        if raw is None:
            if spec.get("required"):
                raise CapabilityError("INVALID_ARGUMENT", f"缺少必填参数: {name}")
            continue
        if ptype in MEDIA_TYPES:
            merged[name] = resolve_media(api_key, raw, work_dir)
        elif ptype == "enum":
            values = spec.get("values") or {}
            if str(raw) not in values:
                raise CapabilityError("INVALID_ARGUMENT",
                                      f"参数 {name}={raw} 不在 {sorted(values)} 内")
            merged[name] = values[str(raw)]
        elif ptype == "boolean":
            merged[name] = bool(raw)
        elif ptype == "number":
            merged[name] = raw
        else:
            merged[name] = str(raw)

    for name, value in merged.items():
        spec = params[name]
        node_id, field = spec["node"], spec["field"]
        if node_id not in wf:
            raise CapabilityError("WORKFLOW_NOT_FOUND",
                                  f"清单指向不存在的节点 {node_id}（参数 {name}）")
        wf[node_id].setdefault("inputs", {})[field] = value
    return wf


def submit(api_key: str, workflow: dict) -> str:
    payload = {"apiKey": api_key, "workflowId": WORKFLOW_ID_PLACEHOLDER,
               "workflow": json.dumps(workflow), "nodeInfoList": []}
    body = _post(f"{RH_HOST}/task/openapi/create", api_key, payload, timeout=90, retries=2)
    if body.get("code") != 0:
        code = body.get("code")
        raise CapabilityError(ERROR_MAP.get(code, "UPSTREAM_FAILED"),
                              f"{code} {body.get('msg')}", upstream=body)
    return body["data"]["taskId"]


def query(api_key: str, rh_task_id: str) -> dict:
    return _post(f"{RH_HOST}/task/openapi/outputs", api_key,
                 {"apiKey": api_key, "taskId": rh_task_id}, timeout=60, retries=1)


def normalize(api_key: str, manifest: dict, rh_resp: dict) -> dict:
    """RunningHub outputs 响应 → 能力单元统一状态。"""
    code = rh_resp.get("code")
    if code == 804:
        return {"task_status": "RUNNING"}
    if code == 813:
        return {"task_status": "PENDING"}
    if code == 0:
        outputs = []
        usage = {}
        for item in rh_resp.get("data") or []:
            if not isinstance(item, dict) or not item.get("fileUrl"):
                continue
            if item.get("nodeId") in (manifest.get("outputNodes") or []):
                outputs.append({"url": item["fileUrl"], "type": manifest.get("output", "file"),
                                "sourceNodeId": item.get("nodeId")})
            if usage == {} and item.get("consumeCoins") is not None:
                usage = {"runtime_seconds": item.get("taskCostTime"),
                         "coins": item.get("consumeCoins"),
                         "money": item.get("consumeMoney")}
        return {"task_status": "SUCCEEDED", "outputs": outputs, "usage": usage}
    reason = (rh_resp.get("data") or {}).get("failedReason") or {}
    if isinstance(reason, str):
        try:
            reason = json.loads(reason)
        except ValueError:
            pass
    return {"task_status": "FAILED",
            "error": {"code": ERROR_MAP.get(code, "UPSTREAM_FAILED"),
                      "message": f"{reason.get('node_name')}: {reason.get('exception_message')}"
                      if reason else rh_resp.get("msg"),
                      "upstream_code": code,
                      "upstream_node": reason.get("node_name") if reason else None}}
