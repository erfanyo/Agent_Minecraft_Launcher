# -*- coding: utf-8 -*-
"""
插件 ed25519 签名 / 验签(溯源 + 完整性校验)。

**定位(用户确认)**:AI 生成插件的问题主要是"执行坏了",恶意代码少见;
所以签名/密钥的核心价值是【溯源 + 信任分级】,不是防恶意。验签通过 →
标"官方/签名可信";无签名(如 AI 生成)→ 标"未审核",衔接 plugin_manager 的审计。

**算法**:ed25519(非对称)。作者用私钥签,启动器只用公钥验(验签≠解密,无需私钥)。
依赖:优先用 cryptography(正规);未装则降级为"无法验签 → 标未审核"(安全默认,不崩)。

**作者私钥维护**:见 project-root `私钥维护.md`(不提交 GitHub)。
公钥 = 作者的 ed25519 公钥(base64),写死在下面 PLUGIN_PUBKEY;换公钥 = 改这里 + 发版。
"""
import base64
import hashlib

# 作者(启动器作者)的 ed25519 公钥(base64)。占位:正式公钥生成后替换。
PLUGIN_PUBKEY = ""   # e.g. "MCowBQYDK2VwAyEA...." (base64 of 32-byte pubkey)

# 溯源:签名里带的 author_id(谁签的),验签后读出。
_AUTHOR_ID = "erfanyo"
_SIG_SCHEME = "ed25519v1"   # 签名算法版本(进签名文本头,防止跨算法误验)


def _crypto():
    """尝试导入 cryptography;未装返回 None(降级)。"""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey, Ed25519PublicKey)
        from cryptography.hazmat.primitives import serialization
        return (Ed25519PrivateKey, Ed25519PublicKey, serialization)
    except Exception:
        return None


def _decoded(pubkey_b64: str):
    """解码公钥 base64 → raw 32 字节;失败返回 None。"""
    if not pubkey_b64:
        return None
    try:
        return base64.b64decode(pubkey_b64)
    except Exception:
        return None


def _pubkey_obj(raw: bytes):
    """raw 32 字节公钥 → Ed25519PublicKey 对象。"""
    _c = _crypto()
    if _c is None:
        return None
    _e, _p, serialization = _c
    try:
        return _p.from_public_bytes(raw)
    except Exception:
        return None


# ---------------- 签名(作者/发布用,不进启动器运行时) ----------------
def sign_plugin(code: str, privkey_b64: str, author_id: str = _AUTHOR_ID) -> str:
    """用作者私钥对插件代码签名,返回签名文本(base64)。

    privkey_b64:作者 ed25519 私钥(base64,含 PKCS8 或 raw)。仅在发布脚本用。
    output:{"scheme":"ed25519v1","author":"<author_id>","sig":"<base64>"} 转 JSON 字符串。
    """
    import json
    _c = _crypto()
    if _c is None:
        raise RuntimeError("需要 cryptography 库才能签名")
    _e, _p, serialization = _c
    # 私钥:接受 raw 32 字节或 PKCS8 DER
    raw = base64.b64decode(privkey_b64)
    try:
        key = _e.from_private_bytes(raw)
    except Exception:
        key = serialization.load_der_private_key(raw, password=None)
    # 对"代码字节 + 作者 + scheme"签名(绑定作者,防换 author)
    data = (code + "\x00" + author_id + "\x00" + _SIG_SCHEME).encode("utf-8")
    sig = key.sign(data)
    return json.dumps({"scheme": _SIG_SCHEME, "author": author_id,
                       "sig": base64.b64encode(sig).decode("ascii")})


# ---------------- 验签(启动器运行时) ----------------
def verify_plugin(code: str, sig_json: str) -> tuple:
    """验签插件代码。返回 (ok: bool, author: str)。

    - cryptography 未装 / 公钥未配置 / 签名缺失 → (False, "")  (= 未审核,安全默认)
    - 验签通过 → (True, author_id)
    - 验签失败 → (False, author_id)  (作者对得上但签名无效=可能被改)
    """
    import json
    if not PLUGIN_PUBKEY or not sig_json:
        return False, ""
    try:
        sig = json.loads(sig_json)
    except Exception:
        return False, ""
    scheme = sig.get("scheme", "")
    author = sig.get("author", "")
    sig_b64 = sig.get("sig", "")
    if scheme != _SIG_SCHEME or not sig_b64:
        return False, author
    raw_pub = _decoded(PLUGIN_PUBKEY)
    pub = _pubkey_obj(raw_pub) if raw_pub else None
    if pub is None:
        return False, author      # cryptography 未装或无公钥 → 未审核
    data = (code + "\x00" + author + "\x00" + _SIG_SCHEME).encode("utf-8")
    try:
        pub.verify(base64.b64decode(sig_b64), data)
        return True, author
    except Exception:
        return False, author


def is_crypto_available() -> bool:
    """是否装了 cryptography(决定验签能力)。"""
    return _crypto() is not None


def generate_keypair() -> tuple:
    """生成一对 ed25519 密钥,返回 (privkey_b64, pubkey_b64)。仅作者生成用。"""
    _c = _crypto()
    if _c is None:
        raise RuntimeError("需要 cryptography 库")
    _e, _p, serialization = _c
    priv = _e.generate()
    pub = priv.public_key()
    priv_b64 = base64.b64encode(priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())).decode("ascii")
    pub_b64 = base64.b64encode(pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")
    return priv_b64, pub_b64
