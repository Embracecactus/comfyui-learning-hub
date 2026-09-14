"""能力单元服务层：引擎 + 任务库 + 轮询线程 + 产物转存。"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from engine import CapabilityError, load_base_workflow, load_manifest, normalize, query, submit, build_workflow


class CapabilityService:
    def __init__(self, config: dict, manifests_dir: Path, db_path: Path,
                 artifacts_dir: Path, repo_root: Path):
        from store import TaskStore
        self.api_key = config["apiKey"]
        self.repo_root = Path(repo_root)
        self.artifacts_dir = Path(artifacts_dir)
        self.store = TaskStore(db_path)
        self.manifests: dict[str, dict] = {}
        for p in sorted(Path(manifests_dir).glob("*.json")):
            m = load_manifest(p)
            self.manifests[m["capability"]] = m
        self._polling = threading.Event()
        self._poller = threading.Thread(target=self._poll_loop, daemon=True)

    # ---------- 能力目录 ----------
    def list_capabilities(self) -> list[dict]:
        out = []
        for m in self.manifests.values():
            out.append({
                "capability": m["capability"],
                "title": m.get("title", m["capability"]),
                "output": m.get("output", "file"),
                "params": {name: {
                    "type": spec.get("type", "string"),
                    "required": bool(spec.get("required")),
                    "default": spec.get("default"),
                    "values": sorted(spec["values"]) if spec.get("values") else None,
                } for name, spec in m["params"].items()},
            })
        return out

    # ---------- 创建 ----------
    def create_task(self, capability: str, request: dict) -> dict:
        if capability not in self.manifests:
            raise CapabilityError("INVALID_ARGUMENT",
                                  f"未知能力 {capability}，可用: {sorted(self.manifests)}")
        manifest = self.manifests[capability]
        task_id = self.store.create(capability, request)
        try:
            base = load_base_workflow(manifest, self.repo_root)
            work_dir = self.artifacts_dir / task_id / "media"
            workflow = build_workflow(self.api_key, manifest, base, request, work_dir)
            rh_task_id = submit(self.api_key, workflow)
            self.store.update(task_id, rh_task_id=rh_task_id, status="RUNNING")
            if not self._polling.is_set():
                self._polling.set()
                self._poller.start()
            return {"task_id": task_id, "task_status": "PENDING",
                    "upstream_task_id": rh_task_id}
        except CapabilityError as e:
            self.store.update(task_id, status="FAILED",
                              error=json.dumps({"code": e.code, "message": str(e),
                                                "upstream": e.upstream}, ensure_ascii=False))
            raise

    # ---------- 查询 ----------
    def get_task(self, task_id: str) -> dict | None:
        t = self.store.get(task_id)
        if not t:
            return None
        out = {"task_id": t["task_id"], "capability": t["capability"],
               "task_status": t["status"],
               "created_at": t["created_at"], "upstream_task_id": t.get("rh_task_id")}
        if t.get("outputs"):
            out["output"] = t["outputs"]
        if t.get("usage"):
            out["usage"] = t["usage"]
        if t.get("error"):
            out["error"] = t["error"]
        return out

    # ---------- 轮询 ----------
    def poll_once(self) -> int:
        """查一轮未完成任务，返回仍在途数量。"""
        inflight = 0
        for t in self.store.pending_with_rh_id():
            try:
                resp = query(self.api_key, t["rh_task_id"])
            except Exception:
                inflight += 1
                continue
            state = normalize(self.api_key, self.manifests[t["capability"]], resp)
            if state["task_status"] == "SUCCEEDED":
                outputs = self._collect(t, state)
                self.store.update(t["task_id"], status="SUCCEEDED",
                                  outputs=json.dumps(outputs, ensure_ascii=False),
                                  usage=json.dumps(state.get("usage") or {}, ensure_ascii=False))
            elif state["task_status"] == "FAILED":
                self.store.update(t["task_id"], status="FAILED",
                                  error=json.dumps(state.get("error") or {}, ensure_ascii=False))
            else:
                self.store.update(t["task_id"], status=state["task_status"])
                inflight += 1
        return inflight

    def _collect(self, task: dict, state: dict) -> list[dict]:
        """下载产物到本地 artifacts（OSS 转存在此处接入），返回本地+远程地址。"""
        out = []
        for item in state.get("outputs") or []:
            dest = None
            try:
                d = self.artifacts_dir / task["task_id"]
                d.mkdir(parents=True, exist_ok=True)
                suffix = ".mp4" if item.get("type") == "video" else ".png"
                dest = d / f"output{suffix}"
                with urllib.request.urlopen(item["url"], timeout=300) as r, dest.open("wb") as f:
                    f.write(r.read())
            except Exception:
                dest = None
            out.append({"type": item.get("type"),
                        "url": item["url"],
                        "local_path": str(dest) if dest else None})
        return out

    def _poll_loop(self, interval: float = 5.0):
        while self._polling.is_set():
            try:
                if self.poll_once() == 0:
                    self._polling.clear()
                    break
            except Exception:
                pass
            time.sleep(interval)
