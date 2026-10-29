# -*- coding: utf-8 -*-
"""MCSManager API adapter (opt-in).

Wraps the ``mcsmapi`` PyPI package so AMCL can talk to a local or remote
MCSManager instance.  The package is **not** a hard dependency — all public
functions return a clear error when ``mcsmapi`` is not installed.

Settings keys (in ``settings.json``):
- ``mcsmanager_url``:  MCSManager panel URL (e.g. ``http://127.0.0.1:23330``)
- ``mcsmanager_apikey``: API key (preferred over username/password)
- ``mcsmanager_username`` / ``mcsmanager_password``: account login (fallback)

Usage::

    from mcsmanager_adapter import MCSManagerClient
    client = MCSManagerClient(url="http://127.0.0.1:23330", apikey="...")
    if client.connect():
        for inst in client.list_instances():
            print(inst["name"], inst["status"])
"""
from __future__ import annotations

from typing import Any


def _require_mcsmapi():
    """Import mcsmapi or raise a clear error."""
    try:
        import mcsmapi
        return mcsmapi
    except ImportError:
        raise ImportError(
            "MCSManager 适配需要 mcsmapi 包。安装: pip install mcsmapi\n"
            "MCSManager 安装: https://mcsmanager.com/"
        )


# Status enum values from mcsmapi (mirrors mcsmapi.models.instance.Status)
_STATUS_NAMES = {-1: "忙碌", 0: "停止", 1: "正在停止", 2: "正在启动", 3: "运行中"}


def _safe(obj, *attrs, default=None):
    """Safely drill into a pydantic model or dict."""
    for attr in attrs:
        if obj is None:
            return default
        if isinstance(obj, dict):
            obj = obj.get(attr, default)
        else:
            obj = getattr(obj, attr, default)
    return obj


class MCSManagerClient:
    """Stateful connection to one MCSManager panel.

    Call :meth:`connect` before any operation.  All methods raise
    ``ConnectionError`` if the panel is unreachable.
    """

    def __init__(
        self,
        url: str = "",
        apikey: str = "",
        username: str = "",
        password: str = "",
        timeout: int = 8,
    ):
        self.url = url.rstrip("/")
        self.apikey = apikey
        self.username = username
        self.password = password
        self.timeout = timeout
        self._api = None  # MCSMAPI instance, set by connect()

    # ---- connection ----

    def connect(self) -> bool:
        """Authenticate with the panel.  Returns True on success."""
        mcsmapi = _require_mcsmapi()
        if not self.url:
            raise ValueError("MCSManager URL 未配置。设置 mcsmanager_url。")
        self._api = mcsmapi.MCSMAPI(self.url, timeout=self.timeout)
        if self.apikey:
            self._api.login_with_apikey(self.apikey)
        elif self.username and self.password:
            self._api.login(self.username, self.password)
        else:
            raise ValueError("需要 API Key 或用户名+密码。设置 mcsmanager_apikey 或 mcsmanager_username/password。")
        return True

    def _ensure(self):
        if self._api is None:
            raise ConnectionError("未连接到 MCSManager。先调 connect()。")

    # ---- daemons / nodes ----

    def list_daemons(self) -> list[dict]:
        """Return all daemon nodes as dicts with ``uuid``, ``ip``, ``port``, ``available``."""
        self._ensure()
        try:
            daemons = self._api.daemon.info()
        except Exception as e:
            raise ConnectionError(f"获取节点列表失败: {e}")
        result = []
        for d in daemons:
            result.append({
                "uuid": getattr(d, "uuid", ""),
                "ip": getattr(d, "ip", ""),
                "port": getattr(d, "port", 0),
                "available": getattr(d, "available", False),
                "remarks": getattr(d, "remarks", ""),
            })
        return result

    # ---- instances ----

    def list_instances(self, daemon_id: str = "", page: int = 1, page_size: int = 50) -> list[dict]:
        """List instances on a specific daemon or all daemons.

        If *daemon_id* is empty, discovers all daemons and aggregates.
        """
        self._ensure()
        daemons = self.list_daemons() if not daemon_id else [{"uuid": daemon_id}]
        result = []
        for d in daemons:
            did = d["uuid"]
            try:
                search = self._api.instance.search(did, page=page, page_size=page_size)
                for inst in getattr(search, "data", []):
                    result.append(self._instance_to_dict(inst, did))
            except Exception:
                continue
        return result

    def instance_status(self, daemon_id: str, uuid: str) -> dict:
        """Get detailed status of one instance."""
        self._ensure()
        try:
            detail = self._api.instance.detail(daemon_id, uuid)
            return self._instance_to_dict(detail, daemon_id)
        except Exception as e:
            raise RuntimeError(f"获取实例状态失败: {e}")

    def start_instance(self, daemon_id: str, uuid: str) -> str:
        """Start an instance.  Returns instance UUID."""
        self._ensure()
        try:
            return self._api.instance.start(daemon_id, uuid)
        except Exception as e:
            raise RuntimeError(f"启动失败: {e}")

    def stop_instance(self, daemon_id: str, uuid: str) -> str:
        """Stop an instance (graceful).  Returns instance UUID."""
        self._ensure()
        try:
            return self._api.instance.stop(daemon_id, uuid)
        except Exception as e:
            raise RuntimeError(f"停止失败: {e}")

    def restart_instance(self, daemon_id: str, uuid: str) -> str:
        """Restart an instance.  Returns instance UUID."""
        self._ensure()
        try:
            return self._api.instance.restart(daemon_id, uuid)
        except Exception as e:
            raise RuntimeError(f"重启失败: {e}")

    def kill_instance(self, daemon_id: str, uuid: str) -> str:
        """Force-kill an instance.  Returns instance UUID."""
        self._ensure()
        try:
            return self._api.instance.kill(daemon_id, uuid)
        except Exception as e:
            raise RuntimeError(f"强制停止失败: {e}")

    def send_command(self, daemon_id: str, uuid: str, command: str) -> str:
        """Send a console command to an instance."""
        self._ensure()
        try:
            return self._api.instance.command(daemon_id, uuid, command)
        except Exception as e:
            raise RuntimeError(f"发送指令失败: {e}")

    def get_output(self, daemon_id: str, uuid: str, size: int | None = None) -> str:
        """Get console output / logs from an instance.

        *size* in KiB (1–2048); ``None`` = all available.
        """
        self._ensure()
        try:
            return self._api.instance.get_output(daemon_id, uuid, size=size)
        except Exception as e:
            raise RuntimeError(f"获取日志失败: {e}")

    # ---- convenience ----

    def find_instance_by_name(self, name: str) -> dict | None:
        """Search all daemons for an instance whose nickname contains *name* (case-insensitive)."""
        for inst in self.list_instances():
            if name.lower() in (inst.get("name") or "").lower():
                return inst
        return None

    # ---- internal ----

    @staticmethod
    def _instance_to_dict(inst: Any, daemon_id: str) -> dict:
        """Normalize an InstanceDetail (pydantic model) into a plain dict."""
        cfg = getattr(inst, "config", inst)  # detail has .config; search item may be flat
        status_raw = getattr(inst, "status", -1)
        status_val = int(status_raw) if isinstance(status_raw, (int, float)) else -1
        return {
            "uuid": getattr(inst, "instanceUuid", getattr(inst, "uuid", "")),
            "daemon_id": daemon_id,
            "name": getattr(cfg, "nickname", "") or getattr(inst, "nickname", ""),
            "status": _STATUS_NAMES.get(status_val, "未知"),
            "status_code": status_val,
            "start_command": getattr(cfg, "startCommand", ""),
            "cwd": getattr(cfg, "cwd", ""),
            "type": getattr(cfg, "type", ""),
            "tags": getattr(cfg, "tag", []),
            "started_count": getattr(inst, "started", 0),
            "last_datetime": getattr(cfg, "lastDatetime", 0),
        }


# ---- Settings integration ----

def client_from_settings(settings: dict) -> MCSManagerClient | None:
    """Build a client from launcher settings.  Returns None if not configured."""
    url = (settings.get("mcsmanager_url") or "").strip()
    if not url:
        return None
    return MCSManagerClient(
        url=url,
        apikey=(settings.get("mcsmanager_apikey") or "").strip(),
        username=(settings.get("mcsmanager_username") or "").strip(),
        password=(settings.get("mcsmanager_password") or "").strip(),
    )


def test_connection(settings: dict) -> str:
    """Quick connection test.  Returns a human-readable status string."""
    client = client_from_settings(settings)
    if client is None:
        return "未配置 MCSManager 连接(settings → mcsmanager_url)。"
    try:
        client.connect()
        daemons = client.list_daemons()
        online = sum(1 for d in daemons if d.get("available"))
        return f"连接成功: {len(daemons)} 个节点({online} 在线)。"
    except ImportError as e:
        return str(e)
    except Exception as e:
        return f"连接失败: {e}"