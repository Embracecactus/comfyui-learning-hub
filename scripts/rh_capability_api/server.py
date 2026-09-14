"""通用能力单元 HTTP API（标准库实现，零依赖）。

路由（wan3.0 风格，见 docs/04-电商AI工作流/14 §3 契约）：
  GET  /v1/capabilities          能力目录（参数 schema 自描述）
  POST /v1/tasks                 创建任务 {"capability", "input", "parameters"}
  GET  /v1/tasks/{task_id}       查询任务（状态/产物/用量/错误）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import CapabilityError  # noqa: E402
from service import CapabilityService  # noqa: E402

SERVICE: CapabilityService | None = None


def make_handler(service: CapabilityService):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)

        def do_GET(self):
            if self.path == "/v1/capabilities":
                self._send(200, {"capabilities": service.list_capabilities()})
                return
            m = re.fullmatch(r"/v1/tasks/([\w-]+)", self.path)
            if m:
                task = service.get_task(m.group(1))
                if task is None:
                    self._send(404, {"error": {"code": "TASK_NOT_FOUND",
                                               "message": m.group(1)}})
                else:
                    self._send(200, task)
                return
            self._send(404, {"error": {"code": "NOT_FOUND", "message": self.path}})

        def do_POST(self):
            if self.path != "/v1/tasks":
                self._send(404, {"error": {"code": "NOT_FOUND", "message": self.path}})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                capability = body.get("capability")
                result = service.create_task(capability, body)
                self._send(202, result)
            except CapabilityError as e:
                status = 400 if e.code in ("INVALID_ARGUMENT", "MEDIA_REJECTED") else 402 if e.code == "INSUFFICIENT_BALANCE" else 502
                self._send(status, {"error": {"code": e.code, "message": str(e)}})
            except Exception as e:
                self._send(500, {"error": {"code": "INTERNAL", "message": str(e)[:300]}})

    return Handler


def main():
    ap = argparse.ArgumentParser(description="RunningHub 通用能力单元 API")
    ap.add_argument("--config", required=True, help="config.json（含 apiKey）")
    ap.add_argument("--manifests", required=True, help="清单目录")
    ap.add_argument("--db", required=True)
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8077)
    args = ap.parse_args()

    global SERVICE
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    SERVICE = CapabilityService(config, Path(args.manifests), Path(args.db),
                                Path(args.artifacts), Path(args.repo_root).resolve())
    server = ThreadingHTTPServer((args.host, args.port), make_handler(SERVICE))
    print(f"capability API on http://{args.host}:{args.port}  "
          f"capabilities={sorted(SERVICE.manifests)}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
