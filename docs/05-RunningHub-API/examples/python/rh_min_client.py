#!/usr/bin/env python3
"""RunningHub 最小可复用客户端(仅标准库,零依赖)。

设计:通用传输(鉴权/上传/提交/轮询/取消/下载)与模型参数完全分离。
模型端点与参数来自 docs/05-RunningHub-API/data/runninghub-api-registry.json,
不要把参数硬编码进客户端。

验证状态(2026-09-13):
  - query / 上传 / 工作流与 AI 应用提交:本仓库已用真实 Key 实测通过;
  - 标准模型 API 提交(含 price-preview):个人 Key 返回 1014,
    需企业级-共享 API Key(https://www.runninghub.cn/enterprise-api/consumerApi 创建);
  - 本文件不含任何真实 Key。Key 从环境变量 RH_API_KEY 读取。

用法:
    export RH_API_KEY=...            # 必需
    export RH_API_BASE_URL=...       # 可选,默认 https://www.runninghub.cn/openapi/v2
    python3 rh_min_client.py query <taskId>
    python3 rh_min_client.py run minimax/hailuo-h3/text-to-video \
        '{"prompt":"…","resolution":"768P","duration":"5","ratio":"16:9"}' \
        --local-files prompt=        # 本地媒体字段: 字段名=本地路径
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_BASE_URL = "https://www.runninghub.cn/openapi/v2"
ORIGIN = "https://www.runninghub.cn"          # 工作流/AI 应用旧域接口(不带 /openapi/v2)
NON_TERMINAL = {"CREATE", "QUEUED", "RUNNING"}
TERMINAL_OK = {"SUCCESS"}
TERMINAL_FAIL = {"FAILED", "CANCEL"}
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}


class RHError(RuntimeError):
    pass


class SubmissionUncertain(RHError):
    """提交请求可能已到达服务端;绝不能盲目重试(可能重复扣费)。"""


def _request(url: str, key: str, payload: dict | None = None,
             multipart: tuple[str, str] | None = None, timeout: int = 60,
             retries: int = 3) -> dict:
    """Bearer 鉴权 POST;仅瞬态错误(网络/429/5xx)重试。"""
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
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in TRANSIENT_HTTP and attempt < retries:
                last = RHError(f"HTTP {e.code}: {detail}")
                time.sleep(2 ** attempt)
                continue
            raise RHError(f"HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < retries:
                last = e
                time.sleep(2 ** attempt)
                continue
            raise RHError(f"{type(e).__name__}: {e}") from e
    raise last or RHError("unreachable")


class RunningHubClient:
    """通用任务生命周期客户端。endpoint 与 payload 由调用方按注册表给出。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 poll_interval: float = 5.0, max_poll_seconds: int = 1800):
        self.key = (api_key or os.environ.get("RH_API_KEY", "")).strip()
        if not self.key:
            raise RHError("缺少 API Key:设置 RH_API_KEY 环境变量")
        self.base = (base_url or os.environ.get("RH_API_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")

    # -- 标准模型 API(/openapi/v2) --------------------------------------
    def upload(self, path: str | Path) -> str:
        """本地媒体必须先上传;返回 data.download_url 填入 *Url 字段。"""
        body = _request(f"{self.base}/media/upload/binary", self.key,
                        multipart=("file", str(path)), timeout=300)
        if body.get("code") != 0:
            raise RHError(f"upload failed: {json.dumps(body, ensure_ascii=False)[:300]}")
        return body["data"]["download_url"]

    def price_preview(self, endpoint: str, payload: dict) -> dict:
        """官方预估价,不创建任务、不扣费。个人 Key 会得到 1014。"""
        return _request(f"{self.base}/price-preview/{endpoint}", self.key, payload)

    def submit(self, endpoint: str, payload: dict) -> str:
        try:
            body = _request(f"{self.base}/{endpoint}", self.key, payload,
                            timeout=90, retries=1)
        except RHError as exc:
            raise SubmissionUncertain(f"提交结果不确定,未自动重试:{exc}") from exc
        if body.get("errorCode") or body.get("errorMessage"):
            raise RHError(f"提交被拒绝: {body.get('errorCode')} {body.get('errorMessage')}")
        task_id = body.get("taskId") or body.get("task_id") or body.get("data", {}).get("taskId")
        if not task_id:
            raise SubmissionUncertain(f"响应无 taskId: {json.dumps(body, ensure_ascii=False)[:300]}")
        return str(task_id)

    def query(self, task_id: str) -> dict:
        return _request(f"{self.base}/query", self.key, {"taskId": task_id})

    def poll(self, task_id: str) -> dict:
        deadline = time.monotonic() + self.max_poll_seconds
        last = None
        while time.monotonic() < deadline:
            body = self.query(task_id)
            status = str(body.get("status") or "").upper()
            if status != last:
                print(f"[{time.strftime('%H:%M:%S')}] {task_id} -> {status or '?'}", flush=True)
                last = status
            if status in TERMINAL_OK or status in TERMINAL_FAIL:
                return body
            time.sleep(self.poll_interval)
        raise RHTimeout(task_id)

    class RHTimeout(RHError):
        def __init__(self, task_id: str):
            super().__init__(f"轮询超时;本地超时≠平台任务失败,保留 taskId 事后 query: {task_id}")
            self.task_id = task_id

    def result_urls(self, final: dict) -> list[str]:
        return [u for u in (i.get("url") or i.get("outputUrl")
                            for i in final.get("results") or []) if u]

    def run(self, endpoint: str, payload: dict, local_files: dict | None = None) -> dict:
        """完整生命周期:本地媒体上传 → 提交 → 轮询终态。"""
        payload = dict(payload)
        for field, path in (local_files or {}).items():
            payload[field] = self.upload(path)
        preview = self.price_preview(endpoint, payload)   # 仅预估,不扣费
        print(f"[price-preview] errorCode={preview.get('errorCode')!r} "
              f"estimate={preview.get('estimatedPrice')!r}")
        task_id = self.submit(endpoint, payload)
        print(f"[submit] taskId={task_id}")
        final = self.poll(task_id)
        return {"taskId": task_id, "final": final, "urls": self.result_urls(final),
                "usage": final.get("usage")}

    # -- 工作流 / AI 应用 API(/task/openapi,个人 Key 可用) --------------
    def workflow_create(self, workflow_id: str, node_info_list: list[dict] | None = None,
                        webhook_url: str | None = None, instance_type: str | None = None) -> str:
        payload: dict = {"apiKey": self.key, "workflowId": str(workflow_id),
                         "nodeInfoList": node_info_list or []}
        if webhook_url:
            payload["webhookUrl"] = webhook_url
        if instance_type:
            payload["instanceType"] = instance_type
        body = _request(f"{ORIGIN}/task/openapi/create", self.key, payload,
                        timeout=90, retries=1)
        if body.get("code") != 0:
            raise RHError(f"create failed code={body.get('code')} msg={body.get('msg')}")
        return str(body["data"]["taskId"])

    def ai_app_run(self, webapp_id: str, node_info_list: list[dict]) -> str:
        payload = {"apiKey": self.key, "webappId": str(webapp_id),
                   "nodeInfoList": node_info_list}
        body = _request(f"{ORIGIN}/task/openapi/ai-app/run", self.key, payload,
                        timeout=90, retries=1)
        if body.get("code") != 0:
            raise RHError(f"ai-app run failed code={body.get('code')} msg={body.get('msg')}")
        return str(body["data"]["taskId"])

    def workflow_outputs(self, task_id: str) -> dict:
        """deprecated 但含成本字段(taskCostTime/consumeCoins/failedReason)。"""
        return _request(f"{ORIGIN}/task/openapi/outputs", self.key,
                        {"apiKey": self.key, "taskId": task_id})

    def workflow_cancel(self, task_id: str) -> dict:
        return _request(f"{ORIGIN}/task/openapi/cancel", self.key,
                        {"apiKey": self.key, "taskId": task_id})


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "query":
        print(json.dumps(RunningHubClient().query(argv[1]), ensure_ascii=False, indent=2))
        return 0
    if len(argv) >= 3 and argv[0] == "run":
        payload = json.loads(argv[2])
        result = RunningHubClient().run(argv[1], payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
