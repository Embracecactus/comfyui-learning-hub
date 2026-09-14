#!/usr/bin/env python3
"""RunningHub 标准模型 API client（遵循 developer-kit rh-api-contract.md）。

生命周期：upload 本地媒体 → submit 模型端点拿 taskId → poll /query 到终态。
终态：SUCCESS 成功 / FAILED、CANCEL 失败；CREATE、QUEUED、RUNNING 非终态。
重试策略：仅瞬态错误（网络、HTTP 429、5xx）重试，业务错误不重试。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_BASE_URL = "https://www.runninghub.cn/openapi/v2"
NON_TERMINAL = {"CREATE", "QUEUED", "RUNNING"}
SUCCESS = "SUCCESS"
FAILURE = {"FAILED", "CANCEL"}
TRANSIENT_HTTP = {429, 500, 502, 503, 504}


class RHError(RuntimeError):
    pass


class RHTimeout(RHError):
    def __init__(self, task_id: str, msg: str):
        super().__init__(msg)
        self.task_id = task_id


def _post(url: str, api_key: str, payload: dict | None = None,
          multipart: tuple | None = None, timeout: int = 60, retries: int = 3) -> dict:
    """POST with Bearer auth. Returns parsed JSON. Retries transient errors only."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            if multipart:
                boundary = uuid.uuid4().hex
                field_name, file_path = multipart
                data = (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; '
                    f'filename="{Path(file_path).name}"\r\n'
                    f'Content-Type: application/octet-stream\r\n\r\n'
                ).encode() + Path(file_path).read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                }
            else:
                data = json.dumps(payload).encode() if payload is not None else b"{}"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
            req = urllib.request.Request(url, data=data, method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass
            if e.code in TRANSIENT_HTTP and attempt < retries:
                last_err = RHError(f"HTTP {e.code} (transient): {body}")
                time.sleep(2 ** attempt)
                continue
            raise RHError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < retries:
                last_err = RHError(f"transient: {type(e).__name__} {e}")
                time.sleep(2 ** attempt)
                continue
            raise RHError(f"{type(e).__name__}: {e}") from e
    raise last_err or RHError("unreachable")


class RunningHubClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL,
                 poll_interval: float = 5.0, max_poll_seconds: int = 1500):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.max_poll_seconds = max_poll_seconds

    def upload(self, path: str | Path) -> str:
        """POST /media/upload/binary → data.download_url（契约规定本地文件必须先上传）。"""
        body = _post(f"{self.base_url}/media/upload/binary", self.api_key,
                     multipart=("file", str(path)), timeout=300)
        if body.get("code") != 0:
            raise RHError(f"upload failed: {json.dumps(body, ensure_ascii=False)}")
        return body["data"]["download_url"]

    def submit(self, endpoint: str, payload: dict) -> str:
        body = _post(f"{self.base_url}/{endpoint.lstrip('/')}", self.api_key, payload)
        task_id = body.get("taskId") or body.get("task_id")
        if not task_id:
            raise RHError(f"submit failed (no taskId): {json.dumps(body, ensure_ascii=False)}")
        return task_id

    def query(self, task_id: str) -> dict:
        return _post(f"{self.base_url}/query", self.api_key, {"taskId": task_id})

    def poll(self, task_id: str, on_status=None) -> dict:
        """轮询到终态；超时抛 RHTimeout（携带 task_id 供事后查询）。"""
        deadline = time.time() + self.max_poll_seconds
        last = None
        while time.time() < deadline:
            body = self.query(task_id)
            status = body.get("status", "")
            if status != last:
                line = f"[{time.strftime('%H:%M:%S')}] status={status or '?'}"
                if body.get("errorCode"):
                    line += f" errorCode={body['errorCode']} errorMessage={body['errorMessage']}"
                print(line)
                if on_status:
                    on_status(body)
                last = status
            if status == SUCCESS:
                return body
            if status in FAILURE:
                return body
            time.sleep(self.poll_interval)
        raise RHTimeout(task_id, f"polling exceeded {self.max_poll_seconds}s, taskId={task_id}")

    def run(self, endpoint: str, payload: dict,
            local_files: dict | None = None) -> dict:
        """完整生命周期：上传本地媒体 → 提交 → 轮询。返回最终原始响应。"""
        payload = dict(payload)
        for field, files in (local_files or {}).items():
            if isinstance(files, (str, Path)):
                payload[field] = self.upload(files)
            else:
                payload[field] = [self.upload(f) for f in files]
        print(f"[submit] {endpoint} payload keys: {sorted(payload)}")
        task_id = self.submit(endpoint, payload)
        print(f"[submit] taskId={task_id}")
        return self.poll(task_id)


def extract_urls(final: dict) -> list[str]:
    urls = []
    for item in final.get("results") or []:
        u = item.get("url") or item.get("outputUrl")
        if u:
            urls.append(u)
    return urls
