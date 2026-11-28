"""规范 JSON 序列化与哈希计算。

共同契约中的内容哈希（recipe_hash、device_config_hash）都基于
“规范 JSON 字节串”计算，规则见 docs/contracts/README.md 第 6 节：

- UTF-8 编码，无 BOM；
- 对象键按码点升序排序；
- 分隔符为 ``,`` 与 ``:``，无任何空白；
- 数值按源文本原样保留（生成端必须先写出规范形式再计算哈希）；
- 不允许 NaN/Infinity。

Kotlin 端 ``org.mirrorchecker.contracts.JsonUtil.canonicalJson`` 实现同一规则，
两端对同一对象必须产生完全相同的字节串。
"""

from __future__ import annotations

import hashlib
import json

from .contracts import ContractError


def canonical_json_bytes(obj: object) -> bytes:
    """把已解析的 JSON 对象序列化为规范字节串。"""
    try:
        text = json.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except ValueError as exc:  # 含 NaN/Infinity
        raise ContractError(f"对象无法写出规范 JSON：{exc}") from exc
    return text.encode("utf-8")


class _NumberToken(str):
    """JSON 解码器已经校验过的数值原文。"""


def _canonical_source_value(value: object) -> str:
    if isinstance(value, _NumberToken):
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(
            _canonical_source_value(key) + ":" + _canonical_source_value(value[key])
            for key in sorted(value)
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_canonical_source_value(item) for item in value) + "]"
    return canonical_json_bytes(value).decode("utf-8")


def source_object_hash(data: bytes, *, field: str | None = None, exclude: str | None = None) -> str:
    """按包内原文校验既有摘要，保留数值的指数、尾零与负零。"""
    document = json.loads(data, parse_float=_NumberToken, parse_int=_NumberToken)
    obj = document if field is None else document[field]
    if exclude is not None:
        obj = {key: value for key, value in obj.items() if key != exclude}
    return sha256_hex(_canonical_source_value(obj).encode("utf-8"))


def sha256_hex(data: bytes) -> str:
    """计算字节串的 SHA-256（小写十六进制）。"""
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(obj: object) -> str:
    """计算对象规范 JSON 的 SHA-256。"""
    return sha256_hex(canonical_json_bytes(obj))


def hash_object_excluding(obj: dict, key: str) -> str:
    """计算“除指定键外”的规范哈希，用于自引用哈希字段。"""
    core = {k: v for k, v in obj.items() if k != key}
    return canonical_sha256(core)
