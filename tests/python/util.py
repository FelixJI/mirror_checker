"""测试工具：读取范例包并构造被篡改的变体。

``rewrite`` 生成新的 ZIP 字节：按 ``changes`` 替换/删除条目；
``fix_manifest=True`` 时同步更新 session.json 清单中的大小与哈希，
使篡改通过哈希检查，从而暴露更深层的契约错误。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from mirror_core.canonical import sha256_hex

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_session_v1.zip"


def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def read_entries(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def rewrite(
    data: bytes,
    changes: dict[str, bytes | None],
    *,
    fix_manifest: bool = True,
) -> bytes:
    entries = read_entries(data)
    for name, content in changes.items():
        if content is None:
            entries.pop(name, None)
        else:
            entries[name] = content

    if fix_manifest and "session.json" in entries:
        session = json.loads(entries["session.json"])
        kept = []
        for entry in session["files"]:
            if entry["path"] not in entries:
                continue
            content = entries[entry["path"]]
            kept.append(
                {
                    "path": entry["path"],
                    "sha256": sha256_hex(content),
                    "size_bytes": len(content),
                }
            )
        session["files"] = kept
        entries["session.json"] = _dumps(session)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def edit_json(data: bytes, mutate) -> bytes:
    """对包内某个 JSON 应用 ``mutuate(obj) -> obj`` 后返回新字节。"""
    obj = json.loads(data)
    obj = mutate(obj)
    return _dumps(obj)


def _dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
