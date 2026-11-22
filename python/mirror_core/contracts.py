"""共同数据契约：版本、单位、坐标方向、状态与格式常量。

本模块与 ``schemas/`` 下的 JSON Schema 共同构成 PR-01 的数据契约。
规范说明见 ``docs/contracts/README.md``。两端（Python / Kotlin）各自以
本机实现强制同一套规则；不一致时抛出 :class:`ContractError`，
错误消息以“文件路径: 字段路径”开头，便于定位。

本模块只依赖 Python 标准库，保证采集端与回放端零运行时依赖。
"""

from __future__ import annotations

import re

#: 当前契约版本。主版本不一致即拒绝解析；次版本向后兼容。
SCHEMA_VERSION = "1.0.0"

#: 数据包种类
PACKAGE_KIND_CAPTURE_SESSION = "capture_session"

# ---------------------------------------------------------------------------
# 单位（docs/contracts/README.md 第 2 节）
# ---------------------------------------------------------------------------

UNIT_LENGTH = "m"
UNIT_ANGLE = "rad"
UNIT_TIME = "s"
LENGTH_UNITS = frozenset({UNIT_LENGTH})
ANGLE_UNITS = frozenset({UNIT_ANGLE})

#: 图像坐标单位为像素；屏幕对应坐标为有效发光矩形内的归一化坐标。
IMAGE_COORDINATE_UNIT = "pixel"
SCREEN_COORDINATE_UNIT = "normalized"

# ---------------------------------------------------------------------------
# 坐标变换方向（docs/contracts/README.md 第 3 节）
# ---------------------------------------------------------------------------

#: ``T_A_B`` 表示“把 B 系坐标变换到 A 系”。
TRANSFORM_CONVENTION = "T_A_B"

# ---------------------------------------------------------------------------
# 状态枚举（实施方案 §8.3）
# ---------------------------------------------------------------------------

#: 采集状态
CAPTURE_STATUSES = ("collecting", "complete", "aborted")
#: 传输状态
TRANSFER_STATUSES = ("local_only", "transferring", "verified")
#: 求解任务状态
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
#: 结果支持状态
SUPPORT_STATUSES = ("diagnostic", "local_validated", "global_validated")

#: 数据来源：合成数据必须显式标注，避免被误当作真机实测。
PROVENANCES = ("synthetic", "device")

#: 帧数据格式。首版只允许 8 位无符号原始亮度数组。
FRAME_FORMATS = ("raw8",)

#: 已登记的坐标系标识：M 镜面参考系、C 相机系、D 屏幕系、P 单站局部系、L 布局系。
KNOWN_FRAMES = ("M", "C", "D", "P", "L")

# ---------------------------------------------------------------------------
# 会话包内固定路径（实施方案 §8.1）
# ---------------------------------------------------------------------------

SESSION_MANIFEST_NAME = "session.json"
DEVICE_PATH = "device.json"
CALIBRATION_INDEX_PATH = "calibration/index.json"
LAYOUT_PATH = "layout.json"
RECIPE_PATH = "recipe.json"
EXPERIMENT_PATH = "experiment.json"

_ATTEMPT_DIR_PATTERN = re.compile(r"^patches/(?P<patch>[^/]+)/attempts/(?P<attempt>[^/]+)$")
_ATTEMPT_FILE_PATTERN = re.compile(
    r"^patches/(?P<patch>[^/]+)/attempts/(?P<attempt>[^/]+)"
    r"/(?P<kind>attempt\.json|observations\.json|frames/(?P<frame>[^/]+))$"
)

FRAME_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
#: 纳秒时间戳在 JSON 中必须是十进制字符串，避免 JavaScript 数值精度损失。
NS_TIMESTAMP_PATTERN = re.compile(r"^(0|[1-9][0-9]*)$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_PATTERN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TIMESTAMP_SOURCES = ("REALTIME", "UNKNOWN")


class ContractError(ValueError):
    """数据不符合共同契约。

    消息格式约定为 ``<位置>: <说明>``，位置是包内文件路径（可含字段路径），
    例如 ``patches/P0001/attempts/A001/attempt.json: frames[3]: ...``。
    """


def check_schema_version(value: object, where: str) -> str:
    """校验 schema_version 字段，返回原值。"""
    if not isinstance(value, str):
        raise ContractError(f"{where}: schema_version 必须是字符串，实际为 {type(value).__name__}")
    if value != SCHEMA_VERSION:
        raise ContractError(
            f"{where}: 不支持的 schema_version={value!r}（当前契约版本为 {SCHEMA_VERSION}；"
            "主版本或未知版本必须显式报错，不得静默解析）"
        )
    return value


def check_enum(value: object, allowed: tuple[str, ...] | frozenset[str], field: str, where: str) -> str:
    """校验枚举字段，返回原值。"""
    if value not in allowed:
        allowed_text = "/".join(sorted(allowed))
        raise ContractError(f"{where}: {field}={value!r} 不在允许集合 ({allowed_text}) 内")
    return value  # type: ignore[return-value]


def check_number(value: object, field: str, where: str, *, minimum: float | None = None) -> float:
    """校验有限数值字段，返回 float。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{where}: {field} 必须是数值，实际为 {type(value).__name__}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ContractError(f"{where}: {field} 必须是有限数值，实际为 {number!r}")
    if minimum is not None and number <= minimum:
        raise ContractError(f"{where}: {field}={number!r} 必须大于 {minimum}")
    return number


def check_positive_int(value: object, field: str, where: str) -> int:
    """校验正整数字段，返回 int。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{where}: {field} 必须是整数，实际为 {type(value).__name__}")
    if value <= 0:
        raise ContractError(f"{where}: {field}={value} 必须为正")
    return value


def check_ns_timestamp(value: object, field: str, where: str) -> str:
    """校验纳秒时间戳：十进制字符串。"""
    if not isinstance(value, str) or not NS_TIMESTAMP_PATTERN.match(value):
        raise ContractError(
            f"{where}: {field} 必须是十进制数字字符串（纳秒），实际为 {value!r}；"
            "JSON 数值形式的纳秒时间戳会有精度损失，契约不允许"
        )
    return value


def check_sha256(value: object, field: str, where: str) -> str:
    """校验 sha256 十六进制小写字符串。"""
    if not isinstance(value, str) or not SHA256_PATTERN.match(value):
        raise ContractError(f"{where}: {field} 必须是 64 位小写十六进制 SHA-256 字符串，实际为 {value!r}")
    return value


def check_rel_path(value: object, field: str, where: str) -> str:
    """校验包内相对路径：POSIX 分隔、不得越界。"""
    if not isinstance(value, str) or not value:
        raise ContractError(f"{where}: {field} 必须是非空字符串")
    if "\\" in value or value.startswith("/") or ".." in value.split("/") or value.endswith("/"):
        raise ContractError(f"{where}: {field}={value!r} 必须是包内安全的相对路径（POSIX 分隔、无 ..）")
    return value


def check_timestamp_source(value: object, field: str, where: str) -> str:
    """校验时间戳来源枚举（REALTIME / UNKNOWN 语义见 Android CaptureResult 文档）。"""
    return check_enum(value, _TIMESTAMP_SOURCES, field, where)


def is_frame_id(value: object) -> bool:
    return isinstance(value, str) and FRAME_ID_PATTERN.match(value) is not None


def is_pattern_id(value: object) -> bool:
    return isinstance(value, str) and _PATTERN_ID_PATTERN.match(value) is not None


def is_attempt_path(path: str) -> bool:
    """判断路径是否位于某个 attempt 目录内。"""
    return _ATTEMPT_FILE_PATTERN.match(path) is not None


def attempt_dir_of(patch_id: str, attempt_id: str) -> str:
    return f"patches/{patch_id}/attempts/{attempt_id}"


def attempt_json_path(patch_id: str, attempt_id: str) -> str:
    return f"{attempt_dir_of(patch_id, attempt_id)}/attempt.json"


def observations_json_path(patch_id: str, attempt_id: str) -> str:
    return f"{attempt_dir_of(patch_id, attempt_id)}/observations.json"
