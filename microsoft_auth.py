# -*- coding: utf-8 -*-
"""
微软正版登录(Minecraft Java 版):设备码流 + 令牌链,拿到游戏内凭证。

流程(社区共识,参考 iris/prismlauncher 等做法):
  ① 微软 OAuth 设备码流(Device Code):向 Azure AD 申请 device code,用户在浏览器里输 code 授权;
  ② 微软 access_token → 用它换 Xbox Live 令牌(XBL);
  ③ XBL → XSTS(授权)令牌;
  ④ XSTS → Minecraft 访问令牌(Minecraft services, api.minecraftservices.com);
  ⑤ 用 MC 令牌查 entitlements(游戏所有权校验)并取 profile(name + id)。

client_id:公开的 Mojang/iris client id(Mojang 官方给第三方启动器使用的公开 id),
无需自己注册 Azure 应用即可用。

注意:完整令牌链需要真实网络到 login.microsoftonline.com / xboxlive.com /
api.minecraftservices.com,且登录时必须由用户在浏览器完成授权(本模块弹 device code 提示)。
"""
import json
import random
import string
import time
import urllib.parse
import urllib.request

# 微软 OAuth client_id:优先从配置(settings["ms_client_id"])读——这是【你自己的】
# Microsoft Entra 应用 id,不写死源码、随 config.json(已 gitignore)走。
# 未配置时回退 Mojang 旧公开 id(可能已被微软收回,导致 AADSTS700016;配了自定义即修复)。
_DEFAULT_CLIENT_ID = "00000000402b5328"


def get_client_id() -> str:
    """返回当前生效的微软 OAuth client_id:settings['ms_client_id'] 优先,否则默认。"""
    try:
        from settings import load_settings
        v = (load_settings().get("ms_client_id") or "").strip()
        if v:
            return v
    except Exception:
        pass
    return _DEFAULT_CLIENT_ID


_SCOPE = "service::user.auth.xboxlive.com::MSCS"
# 微软 OAuth 端点
_DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


def _post_json(url: str, data: dict, headers=None) -> dict:
    """POST urlencoded,返回 JSON(失败抛异常,带原因)。"""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {txt[:300]}")
    except Exception as e:
        raise RuntimeError(f"网络请求失败: {type(e).__name__}: {e}")


def _get(url: str, headers=None) -> dict:
    req = urllib.request.Request(url, method="GET")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {txt[:300]}")
    except Exception as e:
        raise RuntimeError(f"网络请求失败: {type(e).__name__}: {e}")


def _random_device_id() -> str:
    """生成设备/会话 id(微软要求)。"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=32))


class MsAuth:
    """封装一次微软正版登录:device code → 轮询 → 令牌链 → MC profile。

    用法:
        auth = MsAuth()
        user_code, verification_uri, interval = auth.start_device_code()   # 给用户去浏览器授权
        result = auth.await_token()   # 轮询直到授权完成(或超时)
        # result = {"username":..., "uuid":..., "access_token":..., "token_type":...}
    """

    def __init__(self):
        self._device_code = None
        self._interval = 5
        self._device_id = _random_device_id()
        self._ms_token = None       # 微软 access_token
        self._ms_refresh = None

    def start_device_code(self) -> dict:
        """启动设备码流,返回 {user_code, verification_uri, interval, message}。"""
        data = {
            "client_id": get_client_id(),
            "scope": _SCOPE,
        }
        r = _post_json(_DEVICE_CODE_URL, data)
        self._device_code = r.get("device_code")
        self._interval = int(r.get("interval", 5))
        return {
            "user_code": r.get("user_code", ""),
            "verification_uri": r.get("verification_uri", ""),
            "verification_uri_complete": r.get("verification_uri_complete", ""),
            "interval": self._interval,
            "message": r.get("message", ""),
        }

    def await_token(self, timeout: float = 600) -> dict:
        """轮询设备码流授权结果,返回 MC 登录信息。
        超时(runtime 超过 timeout)抛 TimeoutError;用户拒绝抛 RuntimeError。"""
        if not self._device_code:
            raise RuntimeError("请先调用 start_device_code()")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = _post_json(_TOKEN_URL, {
                    "client_id": get_client_id(),
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": self._device_code,
                })
                self._ms_token = r.get("access_token")
                self._ms_refresh = r.get("refresh_token")
                if self._ms_token:
                    return self._finish()
            except RuntimeError as e:
                if "authorization_pending" in str(e):
                    pass       # 用户还没授权,继续轮询
                elif "authorization_declined" in str(e):
                    raise RuntimeError("用户拒绝了授权。")
                elif "expired_token" in str(e) or "slow_down" in str(e):
                    pass       # 过期/太快,继续(按 interval 重试)
                else:
                    raise
            time.sleep(self._interval)
        raise TimeoutError("授权超时(用户未在浏览器完成授权)")

    def _finish(self) -> dict:
        """微软 token → XBL → XSTS → MC 令牌 → entitlements + profile。"""
        # 微软 access_token → MC access_token
        ms_token = self._ms_token
        xbl = _post_json("https://user.auth.xboxlive.com/user/authenticate", {
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": "d=%s" % ms_token,
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        })
        xbl_token = xbl.get("Token")
        xbl_uhs = (xbl.get("DisplayClaims") or {}).get("xui", [{}])[0].get("uhs", "")
        if not xbl_token:
            raise RuntimeError("Xbox Live 令牌获取失败")

        xsts = _post_json("https://xsts.auth.xboxlive.com/xsts/authorize", {
            "Properties": {
                "SandboxId": "RETAIL",
                "UserTokens": [xbl_token],
            },
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        })
        xsts_token = xsts.get("Token")
        if not xsts_token:
            raise RuntimeError("XSTS 令牌获取失败")

        mc = _post_json("https://api.minecraftservices.com/authentication/login_with_xbox", {
            "identityToken": "XBL3.0 x=%s;%s" % (xbl_uhs, xsts_token),
        }, headers={"Content-Type": "application/json"})
        mc_token = mc.get("access_token")
        if not mc_token:
            raise RuntimeError("Minecraft 访问令牌获取失败")

        # ① 所有权校验(必须有 Minecraft 授权)
        try:
            ent = _get("https://api.minecraftservices.com/entitlements/mcstore",
                       headers={"Authorization": "Bearer %s" % mc_token})
            items = ent.get("items", [])
        except Exception:
            items = []
        if not items:
            raise RuntimeError("该账号没有 Minecraft Java 版所有权(未购买/未迁移)。")

        # ② 取 profile(name + uuid)
        prof = _get("https://api.minecraftservices.com/minecraft/profile",
                    headers={"Authorization": "Bearer %s" % mc_token})
        name = prof.get("name", "")
        uuid = prof.get("id", "")
        if not name or not uuid:
            raise RuntimeError("获取 Minecraft profile 失败")

        return {
            "username": name,
            "uuid": uuid,
            "access_token": mc_token,
            "refresh_token": self._ms_refresh or "",
            "token_type": "msa",
        }


# 兼容旧名
def microsoft_login_device_code():
    """便捷入口:返回 (auth 实例, 用户需访问的提示)。"""
    auth = MsAuth()
    info = auth.start_device_code()
    return auth, info


def refresh_with_ms_refresh(refresh_token: str) -> dict:
    """用微软 refresh_token 换新的 MC 凭证(免重新登录)。

    步骤:微软 refresh_token → 新微软 access_token → 重跑 XBL→XSTS→MC → 返回新凭证。
    返回 {username, uuid, access_token, refresh_token, token_type}(username/uuid 从 profile 取,
    refresh_token 若无新值则沿用旧的)。失败抛 RuntimeError。
    """
    if not refresh_token:
        raise RuntimeError("没有可用的 refresh_token")
    r = _post_json(_TOKEN_URL, {
        "client_id": _CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": _SCOPE,
    })
    ms_token = r.get("access_token")
    new_refresh = r.get("refresh_token") or refresh_token
    if not ms_token:
        raise RuntimeError("刷新微软令牌失败")
    # 复用令牌链(新建一个临时 auth,把 ms token 塞进去)
    tmp = MsAuth()
    tmp._ms_token = ms_token
    tmp._ms_refresh = new_refresh
    result = tmp._finish()
    result["refresh_token"] = new_refresh
    return result


def download_player_avatar(uuid_str: str, size: int = 64, use_cache: bool = True) -> bytes | None:
    """拉取玩家 3D 头像(头部贴图渲染图),缓存到 AMCL/cache/avatars/<uuid>_<size>.png。

    用公开头像渲染服务(crafatar.com,免费、按 UUID 渲染头);失败返回 None(调用方回退占位头像)。
    uuid 需是无横线的纯 hex(32 位)或标准 UUID;服务都接受。
    """
    if not uuid_str:
        return None
    try:
        import os as _os
        from paths import cache_dir as _cache_dir
        d = _cache_dir("avatars")
        cache_path = _os.path.join(d, "%s_%d.png" % (uuid_str.replace("-", ""), size))
        if use_cache and _os.path.isfile(cache_path):
            with open(cache_path, "rb") as f:
                return f.read()
        uid = uuid_str.replace("-", "")
        url = "https://crafatar.com/avatars/%s?size=%d&overlay" % (uid, size)
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "AgentLauncher/0.4"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if data and len(data) > 100:
            try:
                _os.makedirs(d, exist_ok=True)
                with open(cache_path, "wb") as f:
                    f.write(data)
            except OSError:
                pass
            return data
    except Exception:
        pass
    return None
