"""离线会话包（自包含 ZIP）的解析与契约校验。

包结构遵循实施方案 §8.1：

    session.json                                   清单、状态与引用
    device.json                                    设备能力与配置快照
    calibration/index.json (+ 条目文件)            本次使用的标定内容
    layout.json                                    条带标记布局与镜面参考关系
    recipe.json                                    采集配方（不可变、带哈希）
    patches/<PID>/attempts/<AID>/attempt.json      一次尝试的绑定与逐帧元数据
    patches/<PID>/attempts/<AID>/frames/*.bin      无损帧数据
    patches/<PID>/attempts/<AID>/observations.json 标记角点、IMU 与初步位姿
    experiment.json                                人工操作记录

校验失败一律抛出 :class:`~mirror_core.contracts.ContractError`，
消息以包内路径开头。缺帧、未知单位、变换维度错误、标定/配置不匹配
都必须给出可定位的明确报错（PR-01 验收项）。
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from .canonical import canonical_sha256, hash_object_excluding, sha256_hex
from .contracts import (
    CAPTURE_STATUSES,
    CALIBRATION_INDEX_PATH,
    ContractError,
    DEVICE_PATH,
    EXPERIMENT_PATH,
    FRAME_FORMATS,
    LAYOUT_PATH,
    PACKAGE_KIND_CAPTURE_SESSION,
    PROVENANCES,
    RECIPE_PATH,
    SESSION_MANIFEST_NAME,
    TRANSFORM_CONVENTION,
    TRANSFER_STATUSES,
    UNIT_ANGLE,
    UNIT_LENGTH,
    attempt_json_path,
    check_enum,
    check_ns_timestamp,
    check_number,
    check_positive_int,
    check_rel_path,
    check_schema_version,
    check_sha256,
    check_timestamp_source,
    is_pattern_id,
    observations_json_path,
)
from .transforms import Transform

_PATCHES_PREFIX = "patches/"
_FRAME_FILE_PATTERN = re.compile(r"^frames/[A-Za-z0-9][A-Za-z0-9._-]*$")
_ATTEMPT_FILE_PATTERN = re.compile(
    r"^patches/[^/]+/attempts/[^/]+/(attempt\.json|observations\.json|frames/[^/]+)$"
)
_PATTERN_KINDS = ("fringe", "gray", "mask", "white", "black")


class SessionPackage:
    """一个已通过契约校验的采集会话包。

    用 :meth:`open` 打开；任何契约违规都会在打开阶段抛出
    :class:`~mirror_core.contracts.ContractError`。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.session: dict[str, Any] = {}
        self.device: dict[str, Any] = {}
        self.recipe: dict[str, Any] = {}
        self.layout: dict[str, Any] = {}
        self.calibration_id: str | None = None
        self.experiment: dict[str, Any] = {}
        self.attempts: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 摘要信息
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self.session["session_id"]

    @property
    def provenance(self) -> str:
        return self.session["provenance"]

    @property
    def capture_status(self) -> str:
        return self.session["capture_status"]

    @property
    def manifest_file_count(self) -> int:
        return len(self.session["files"])

    @property
    def total_frames(self) -> int:
        return sum(len(a.get("frames", [])) for a in self.attempts)

    def summary(self) -> dict[str, Any]:
        """供 CLI/工作台展示的摘要。"""
        return {
            "schema_version": self.session["schema_version"],
            "session_id": self.session_id,
            "provenance": self.provenance,
            "capture_status": self.capture_status,
            "transfer_status": self.session["transfer_status"],
            "patches": len(self.session["patches"]),
            "attempts": len(self.attempts),
            "frames": self.total_frames,
            "manifest_files": self.manifest_file_count,
        }

    # ------------------------------------------------------------------
    # 打开与校验入口
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path) -> "SessionPackage":
        """打开并完整校验一个会话 ZIP。"""
        path = Path(path)
        try:
            with zipfile.ZipFile(path) as zf:
                infos = zf.infolist()
                names = [info.filename for info in infos]
                entries = {info.filename: zf.read(info.filename) for info in infos}
        except zipfile.BadZipFile as exc:
            raise ContractError(f"{path}: 不是有效的 ZIP 会话包（{exc}）") from exc

        _check_zip_names(names, path)

        if SESSION_MANIFEST_NAME not in entries:
            raise ContractError(f"{path}: 会话缺少 {SESSION_MANIFEST_NAME}")

        session = _load_json(entries[SESSION_MANIFEST_NAME], SESSION_MANIFEST_NAME)
        package = cls(path)
        _validate(package, session, entries)
        return package


# ----------------------------------------------------------------------
# 内部校验实现
# ----------------------------------------------------------------------


def _load_json(data: bytes, where: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{where}: JSON 解析失败（{exc}）") from exc


def _require_entry(entries: dict[str, bytes], path: str) -> bytes:
    if path not in entries:
        raise ContractError(f"{path}: 契约要求的文件不在包内")
    return entries[path]


def _check_zip_names(names: list[str], path: Path) -> None:
    if len(set(names)) != len(names):
        duplicated = sorted({n for n in names if names.count(n) > 1})
        raise ContractError(f"{path}: ZIP 内存在重名条目 {duplicated}")
    for name in names:
        if name.endswith("/"):
            raise ContractError(f"{path}: 不支持目录条目 {name!r}（清单只登记文件）")


def _validate(package: SessionPackage, session: dict[str, Any], entries: dict[str, bytes]) -> None:
    _validate_session_header(session)
    _validate_manifest(session, entries)
    device = _validate_device(session, entries)
    recipe = _validate_recipe(session, entries, device)
    calibration_id = _validate_calibration(session, entries, device)
    layout = _validate_layout(entries)
    experiment = _validate_experiment(entries)
    attempts = _validate_patches(session, entries, recipe, calibration_id, device)
    _validate_session_completion(session, attempts)

    package.session = session
    package.device = device
    package.recipe = recipe
    package.layout = layout
    package.calibration_id = calibration_id
    package.experiment = experiment
    package.attempts = attempts


def _validate_session_header(session: dict[str, Any]) -> None:
    where = SESSION_MANIFEST_NAME
    if not isinstance(session, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(session.get("schema_version"), where)

    if session.get("package_kind") != PACKAGE_KIND_CAPTURE_SESSION:
        raise ContractError(
            f"{where}: package_kind={session.get('package_kind')!r} 不被支持"
            f"（本契约只描述 {PACKAGE_KIND_CAPTURE_SESSION}）"
        )

    for key in ("session_id", "created_utc"):
        if not isinstance(session.get(key), str) or not session[key]:
            raise ContractError(f"{where}: {key} 必须是非空字符串")
    check_enum(session.get("provenance"), PROVENANCES, "provenance", where)
    check_enum(session.get("capture_status"), CAPTURE_STATUSES, "capture_status", where)
    check_enum(session.get("transfer_status"), TRANSFER_STATUSES, "transfer_status", where)

    _validate_units(session)
    _validate_coordinate_conventions(session)


def _validate_units(session: dict[str, Any]) -> None:
    where = f"{SESSION_MANIFEST_NAME}: units"
    units = session.get("units")
    if not isinstance(units, dict):
        raise ContractError(f"{where}: 必须是对象")
    if units.get("length") != UNIT_LENGTH:
        raise ContractError(
            f"{where}.length: 未知长度单位 {units.get('length')!r}（契约只允许 {UNIT_LENGTH!r}，米）"
        )
    if units.get("angle") != UNIT_ANGLE:
        raise ContractError(
            f"{where}.angle: 未知角度单位 {units.get('angle')!r}（契约只允许 {UNIT_ANGLE!r}，弧度）"
        )


def _validate_coordinate_conventions(session: dict[str, Any]) -> None:
    where = f"{SESSION_MANIFEST_NAME}: coordinate_conventions"
    conv = session.get("coordinate_conventions")
    if not isinstance(conv, dict):
        raise ContractError(f"{where}: 必须是对象")
    if conv.get("transform") != TRANSFORM_CONVENTION:
        raise ContractError(
            f"{where}.transform: 变换方向约定错误，必须声明为 {TRANSFORM_CONVENTION!r}"
            "（from_frame 坐标变换到 to_frame）"
        )
    for key in ("image_coordinates", "screen_coordinates", "mirror_frame"):
        if not isinstance(conv.get(key), str) or not conv[key]:
            raise ContractError(f"{where}.{key}: 必须是非空字符串说明")


def _validate_manifest(session: dict[str, Any], entries: dict[str, bytes]) -> None:
    where = f"{SESSION_MANIFEST_NAME}: files"
    files = session.get("files")
    if not isinstance(files, list):
        raise ContractError(f"{where}: 必须是数组")

    manifest: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(files):
        entry_where = f"{where}[{i}]"
        if not isinstance(entry, dict):
            raise ContractError(f"{entry_where}: 必须是对象")
        path = check_rel_path(entry.get("path"), "path", entry_where)
        if path == SESSION_MANIFEST_NAME:
            raise ContractError(f"{entry_where}: 清单不得登记 {SESSION_MANIFEST_NAME} 自身")
        if path in manifest:
            raise ContractError(f"{entry_where}: 清单重复登记 {path}")
        check_sha256(entry.get("sha256"), "sha256", entry_where)
        size = entry.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ContractError(f"{entry_where}: size_bytes 必须是非负整数")
        manifest[path] = entry

    zip_names = set(entries) - {SESSION_MANIFEST_NAME}
    missing = sorted(set(manifest) - zip_names)
    if missing:
        raise ContractError(
            f"{where}: 清单中的文件在包内不存在（缺文件/缺帧）: {missing[:3]}"
            f"{' 等' if len(missing) > 3 else ''}"
        )
    extra = sorted(zip_names - set(manifest))
    if extra:
        raise ContractError(
            f"{where}: 包内存在未登记文件: {extra[:3]}{' 等' if len(extra) > 3 else ''}"
        )

    for path, entry in manifest.items():
        data = entries[path]
        if len(data) != entry["size_bytes"]:
            raise ContractError(
                f"{path}: 文件大小与清单不一致（清单 {entry['size_bytes']} 字节，实际 {len(data)} 字节）"
            )
        actual = sha256_hex(data)
        if actual != entry["sha256"]:
            raise ContractError(
                f"{path}: 文件 SHA-256 与清单不一致（清单 {entry['sha256']}，实际 {actual}）"
            )


def _validate_device(session: dict[str, Any], entries: dict[str, bytes]) -> dict[str, Any]:
    ref = session.get("device")
    if not isinstance(ref, dict) or ref.get("path") != DEVICE_PATH:
        raise ContractError(f"{SESSION_MANIFEST_NAME}: device.path 必须是 {DEVICE_PATH!r}")
    device = _load_json(_require_entry(entries, DEVICE_PATH), DEVICE_PATH)
    where = DEVICE_PATH
    if not isinstance(device, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(device.get("schema_version"), where)
    if not isinstance(device.get("device_id"), str) or not device["device_id"]:
        raise ContractError(f"{where}: device_id 必须是非空字符串")

    config = device.get("device_config")
    if not isinstance(config, dict):
        raise ContractError(f"{where}: device_config 必须是对象（采集配置快照）")
    recomputed = canonical_sha256(config)
    if device.get("device_config_hash") != recomputed:
        raise ContractError(
            f"{where}: device_config_hash 与 device_config 内容不匹配（配置不匹配；"
            f"登记 {device.get('device_config_hash')!r}，实际 {recomputed!r}）"
        )
    if ref.get("config_hash") != device["device_config_hash"]:
        raise ContractError(
            f"{SESSION_MANIFEST_NAME}: device.config_hash 与 {where} 的 device_config_hash 不一致（配置不匹配）"
        )

    camera = device.get("camera")
    if not isinstance(camera, dict):
        raise ContractError(f"{where}: camera 必须是对象")
    stream = camera.get("stream")
    if not isinstance(stream, dict):
        raise ContractError(f"{where}: camera.stream 必须是对象")
    check_positive_int(stream.get("width_px"), "camera.stream.width_px", where)
    check_positive_int(stream.get("height_px"), "camera.stream.height_px", where)

    display = device.get("display")
    if not isinstance(display, dict):
        raise ContractError(f"{where}: display 必须是对象")
    luminous = display.get("effective_luminous")
    if not isinstance(luminous, dict):
        raise ContractError(f"{where}: display.effective_luminous 必须是对象")
    check_number(luminous.get("width_m"), "display.effective_luminous.width_m", where, minimum=0)
    check_number(luminous.get("height_m"), "display.effective_luminous.height_m", where, minimum=0)
    return device


def _validate_recipe(
    session: dict[str, Any], entries: dict[str, bytes], device: dict[str, Any]
) -> dict[str, Any]:
    ref = session.get("recipe")
    if not isinstance(ref, dict) or ref.get("path") != RECIPE_PATH:
        raise ContractError(f"{SESSION_MANIFEST_NAME}: recipe.path 必须是 {RECIPE_PATH!r}")
    recipe = _load_json(_require_entry(entries, RECIPE_PATH), RECIPE_PATH)
    where = RECIPE_PATH
    if not isinstance(recipe, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(recipe.get("schema_version"), where)
    if not isinstance(recipe.get("recipe_id"), str) or not recipe["recipe_id"]:
        raise ContractError(f"{where}: recipe_id 必须是非空字符串")

    registered = recipe.get("recipe_hash")
    check_sha256(registered, "recipe_hash", where)
    recomputed = hash_object_excluding(recipe, "recipe_hash")
    if registered != recomputed:
        raise ContractError(
            f"{where}: recipe_hash 与配方内容不匹配（配置不匹配；"
            f"登记 {registered}，按当前内容计算为 {recomputed}）"
        )
    if ref.get("recipe_hash") != registered:
        raise ContractError(
            f"{SESSION_MANIFEST_NAME}: recipe.recipe_hash 与 {where} 的 recipe_hash 不一致（配置不匹配）"
        )

    patterns = recipe.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise ContractError(f"{where}: patterns 必须是非空数组")
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    for i, pattern in enumerate(patterns):
        pattern_where = f"{where}: patterns[{i}]"
        if not isinstance(pattern, dict):
            raise ContractError(f"{pattern_where}: 必须是对象")
        pattern_id = pattern.get("pattern_id")
        if not is_pattern_id(pattern_id):
            raise ContractError(f"{pattern_where}: pattern_id={pattern_id!r} 不是合法图案 ID")
        if pattern_id in seen_ids:
            raise ContractError(f"{pattern_where}: pattern_id={pattern_id!r} 重复")
        seen_ids.add(str(pattern_id))
        kind = check_enum(pattern.get("kind"), _PATTERN_KINDS, "kind", pattern_where)
        order = pattern.get("display_order")
        if isinstance(order, bool) or not isinstance(order, int):
            raise ContractError(f"{pattern_where}: display_order 必须是整数")
        if order in seen_orders:
            raise ContractError(f"{pattern_where}: display_order={order} 重复")
        seen_orders.add(order)
        if kind == "fringe":
            check_enum(pattern.get("direction_deg"), (0, 90), "direction_deg", pattern_where)
            check_number(
                pattern.get("frequency_cycles_per_pattern"),
                "frequency_cycles_per_pattern",
                pattern_where,
                minimum=0,
            )
            check_number(pattern.get("phase_shift_rad"), "phase_shift_rad", pattern_where)
        elif kind == "gray":
            check_positive_int(pattern.get("level"), "level", pattern_where)

    repeats = recipe.get("repeats")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ContractError(f"{where}: repeats 必须是 >=1 的整数")

    wait = recipe.get("wait_strategy")
    if not isinstance(wait, dict):
        raise ContractError(f"{where}: wait_strategy 必须是对象")
    check_ns_timestamp(wait.get("timeout_ns"), "wait_strategy.timeout_ns", where)

    applicable_cal = recipe.get("applicable_calibration_id")
    if applicable_cal is not None and not isinstance(applicable_cal, str):
        raise ContractError(f"{where}: applicable_calibration_id 必须是字符串或 null")
    applicable_dev = recipe.get("applicable_device_config_hash")
    check_sha256(applicable_dev, "applicable_device_config_hash", where)
    if applicable_dev != device["device_config_hash"]:
        raise ContractError(
            f"{where}: applicable_device_config_hash 与本次 device_config_hash 不匹配（标定/配置不匹配）"
        )
    return recipe


def _expected_pattern_sequence(recipe: dict[str, Any]) -> list[str]:
    ordered = sorted(recipe["patterns"], key=lambda p: p["display_order"])
    return [p["pattern_id"] for p in ordered] * recipe["repeats"]


def _validate_calibration(
    session: dict[str, Any], entries: dict[str, bytes], device: dict[str, Any]
) -> str | None:
    ref = session.get("calibration")
    if not isinstance(ref, dict) or not isinstance(ref.get("present"), bool):
        raise ContractError(
            f"{SESSION_MANIFEST_NAME}: calibration 必须是含 present 布尔值的对象；"
            "诊断采集可以显式 present=false，但必须声明"
        )
    if not ref["present"]:
        return None

    if ref.get("path") != CALIBRATION_INDEX_PATH:
        raise ContractError(f"{SESSION_MANIFEST_NAME}: calibration.path 必须是 {CALIBRATION_INDEX_PATH!r}")
    index = _load_json(_require_entry(entries, CALIBRATION_INDEX_PATH), CALIBRATION_INDEX_PATH)
    where = CALIBRATION_INDEX_PATH
    if not isinstance(index, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(index.get("schema_version"), where)
    calibration_id = index.get("calibration_id")
    if not isinstance(calibration_id, str) or not calibration_id:
        raise ContractError(f"{where}: calibration_id 必须是非空字符串")
    if ref.get("calibration_id") != calibration_id:
        raise ContractError(
            f"{SESSION_MANIFEST_NAME}: calibration.calibration_id 与索引文件中的 {calibration_id!r} 不一致"
        )

    items = index.get("items")
    if not isinstance(items, list):
        raise ContractError(f"{where}: items 必须是数组")
    for i, item in enumerate(items):
        item_where = f"{where}: items[{i}]"
        if not isinstance(item, dict):
            raise ContractError(f"{item_where}: 必须是对象")
        if not isinstance(item.get("kind"), str) or not item["kind"]:
            raise ContractError(f"{item_where}: kind 必须是非空字符串")
        file_ref = check_rel_path(item.get("file"), "file", item_where)
        item_path = f"calibration/{file_ref}"
        if item_path not in entries:
            raise ContractError(f"{item_where}: 标定条目文件 {item_path} 不在包内")
        _load_json(entries[item_path], item_path)

    conditions = index.get("applicable_conditions")
    if not isinstance(conditions, dict):
        raise ContractError(f"{where}: applicable_conditions 必须是对象")
    if conditions.get("device_config_hash") != device["device_config_hash"]:
        raise ContractError(
            f"{where}: applicable_conditions.device_config_hash 与本次设备配置不匹配（标定/配置不匹配）"
        )
    return calibration_id


def _validate_layout(entries: dict[str, bytes]) -> dict[str, Any]:
    layout = _load_json(_require_entry(entries, LAYOUT_PATH), LAYOUT_PATH)
    where = LAYOUT_PATH
    if not isinstance(layout, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(layout.get("schema_version"), where)
    if not isinstance(layout.get("layout_id"), str) or not layout["layout_id"]:
        raise ContractError(f"{where}: layout_id 必须是非空字符串")

    strips = layout.get("strips")
    if not isinstance(strips, list) or not strips:
        raise ContractError(f"{where}: strips 必须是非空数组")
    seen_tags: set[int] = set()
    for s, strip in enumerate(strips):
        strip_where = f"{where}: strips[{s}]"
        if not isinstance(strip, dict):
            raise ContractError(f"{strip_where}: 必须是对象")
        markers = strip.get("markers")
        if not isinstance(markers, list) or not markers:
            raise ContractError(f"{strip_where}: markers 必须是非空数组")
        for m, marker in enumerate(markers):
            marker_where = f"{strip_where}: markers[{m}]"
            if not isinstance(marker, dict):
                raise ContractError(f"{marker_where}: 必须是对象")
            tag = marker.get("tag_id")
            if isinstance(tag, bool) or not isinstance(tag, int):
                raise ContractError(f"{marker_where}: tag_id 必须是整数")
            if tag in seen_tags:
                raise ContractError(f"{marker_where}: tag_id={tag} 在布局内重复")
            seen_tags.add(tag)
            corners = marker.get("corners_layout_m")
            if not isinstance(corners, list) or len(corners) != 4:
                raise ContractError(
                    f"{marker_where}: corners_layout_m 必须是 4 个三维角点（左上/右上/右下/左下，布局系，米）"
                )
            for c, corner in enumerate(corners):
                _check_vector3(corner, f"{marker_where}: corners_layout_m[{c}]")

    mirror_ref = layout.get("mirror_reference")
    if not isinstance(mirror_ref, dict):
        raise ContractError(f"{where}: mirror_reference 必须是对象")
    Transform.from_mapping(mirror_ref.get("T_M_L"), f"{where}: mirror_reference.T_M_L")
    return layout


def _validate_experiment(entries: dict[str, bytes]) -> dict[str, Any]:
    experiment = _load_json(_require_entry(entries, EXPERIMENT_PATH), EXPERIMENT_PATH)
    where = EXPERIMENT_PATH
    if not isinstance(experiment, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(experiment.get("schema_version"), where)
    entries_list = experiment.get("entries")
    if not isinstance(entries_list, list):
        raise ContractError(f"{where}: entries 必须是数组")
    for i, entry in enumerate(entries_list):
        if not isinstance(entry, dict) or not isinstance(entry.get("note"), str):
            raise ContractError(f"{where}: entries[{i}] 必须是含 note 字符串的对象")
    return experiment


def _validate_patches(
    session: dict[str, Any],
    entries: dict[str, bytes],
    recipe: dict[str, Any],
    calibration_id: str | None,
    device: dict[str, Any],
) -> list[dict[str, Any]]:
    patches = session.get("patches")
    if not isinstance(patches, list):
        raise ContractError(f"{SESSION_MANIFEST_NAME}: patches 必须是数组")

    expected_sequence = _expected_pattern_sequence(recipe)
    recipe_hash = recipe["recipe_hash"]
    device_hash = device["device_config_hash"]
    stream_w = device["camera"]["stream"]["width_px"]
    stream_h = device["camera"]["stream"]["height_px"]

    all_attempts: list[dict[str, Any]] = []
    seen_attempt_paths: set[str] = set()
    for p, patch in enumerate(patches):
        patch_where = f"{SESSION_MANIFEST_NAME}: patches[{p}]"
        if not isinstance(patch, dict):
            raise ContractError(f"{patch_where}: 必须是对象")
        patch_id = patch.get("patch_id")
        if not isinstance(patch_id, str) or not patch_id or "/" in patch_id:
            raise ContractError(f"{patch_where}: patch_id 必须是不含 / 的非空字符串")
        attempts = patch.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ContractError(f"{patch_where}: attempts 必须是非空数组")
        for a, att_ref in enumerate(attempts):
            att_where = f"{patch_where}: attempts[{a}]"
            if not isinstance(att_ref, dict):
                raise ContractError(f"{att_where}: 必须是对象")
            attempt_id = att_ref.get("attempt_id")
            if not isinstance(attempt_id, str) or not attempt_id or "/" in attempt_id:
                raise ContractError(f"{att_where}: attempt_id 必须是不含 / 的非空字符串")
            aj_path = attempt_json_path(patch_id, attempt_id)
            if aj_path in seen_attempt_paths:
                raise ContractError(f"{att_where}: 重复的 attempt 路径 {aj_path}")
            seen_attempt_paths.add(aj_path)
            if att_ref.get("path") != aj_path:
                raise ContractError(f"{att_where}: path 必须是 {aj_path!r}")

            attempt = _load_json(_require_entry(entries, aj_path), aj_path)
            attempt["_patch_id"] = patch_id
            attempt["_path"] = aj_path
            _validate_attempt(
                attempt,
                entries,
                patch_id,
                attempt_id,
                recipe_hash,
                calibration_id,
                device_hash,
                expected_sequence,
                stream_w,
                stream_h,
            )
            all_attempts.append(attempt)

    _check_no_stray_patch_files(session, entries, seen_attempt_paths)
    return all_attempts


def _validate_attempt(
    attempt: dict[str, Any],
    entries: dict[str, bytes],
    patch_id: str,
    attempt_id: str,
    recipe_hash: str,
    calibration_id: str | None,
    device_hash: str,
    expected_sequence: list[str],
    stream_w: int,
    stream_h: int,
) -> None:
    aj_path = attempt_json_path(patch_id, attempt_id)
    where = aj_path
    if not isinstance(attempt, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(attempt.get("schema_version"), where)
    if attempt.get("patch_id") != patch_id or attempt.get("attempt_id") != attempt_id:
        raise ContractError(f"{where}: patch_id/attempt_id 与所在路径不一致")
    check_enum(attempt.get("capture_status"), CAPTURE_STATUSES, "capture_status", where)

    # 绑定校验：recipe_hash / calibration_id / device_config_hash（标定与配置不匹配在此报错）
    if attempt.get("recipe_hash") != recipe_hash:
        raise ContractError(
            f"{where}: attempt 绑定的 recipe_hash 与会话配方不一致（标定/配置不匹配；"
            f"attempt={attempt.get('recipe_hash')!r}，配方={recipe_hash!r}）"
        )
    att_cal = attempt.get("calibration_id")
    if att_cal != calibration_id:
        raise ContractError(
            f"{where}: attempt 绑定的 calibration_id={att_cal!r} 与会话标定 {calibration_id!r} 不一致"
            "（标定/配置不匹配）"
        )
    if attempt.get("device_config_hash") != device_hash:
        raise ContractError(
            f"{where}: attempt 绑定的 device_config_hash 与设备配置不一致（标定/配置不匹配）"
        )

    expected_field = attempt.get("expected_frames")
    if not isinstance(expected_field, list) or not expected_field:
        raise ContractError(f"{where}: expected_frames 必须是非空数组")
    if list(expected_field) != expected_sequence:
        raise ContractError(
            f"{where}: expected_frames 与配方图案序列不一致（配置不匹配）；"
            "expected_frames 必须按 display_order 排列并乘以 repeats"
        )

    frames = attempt.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ContractError(f"{where}: frames 必须是非空数组")

    actual = [f.get("pattern_id") for f in frames if isinstance(f, dict)]
    if actual != expected_sequence:
        missing = [pid for pid in expected_sequence if pid not in actual]
        extra = [pid for pid in actual if pid not in expected_sequence]
        duplicates = sorted({pid for pid in actual if actual.count(pid) > 1})
        details = []
        if missing:
            details.append(f"缺少图案帧 {missing[:3]}{' 等' if len(missing) > 3 else ''}")
        if extra:
            details.append(f"多余图案帧 {extra[:3]}")
        if duplicates:
            details.append(f"重复图案帧 {duplicates[:3]}")
        raise ContractError(
            f"{where}: 帧序列与配方不一致（缺帧/乱序/重复）：{'；'.join(details) or '顺序不匹配'}；"
            f"期望 {len(expected_sequence)} 帧，实际 {len(frames)} 帧"
        )

    base_dir = f"patches/{patch_id}/attempts/{attempt_id}"
    for i, frame in enumerate(frames):
        frame_where = f"{where}: frames[{i}]"
        if not isinstance(frame, dict):
            raise ContractError(f"{frame_where}: 必须是对象")
        if frame.get("frame_index") != i:
            raise ContractError(
                f"{frame_where}: frame_index={frame.get('frame_index')!r} 与数组下标 {i} 不一致（帧序号必须连续）"
            )
        if not is_pattern_id(frame.get("pattern_id")):
            raise ContractError(f"{frame_where}: pattern_id 不是合法图案 ID")
        rel = frame.get("file")
        if not isinstance(rel, str) or not _FRAME_FILE_PATTERN.match(rel):
            raise ContractError(f"{frame_where}: file={rel!r} 必须形如 'frames/<名称>'（位于本 attempt 目录内）")
        fmt = check_enum(frame.get("format"), FRAME_FORMATS, "format", frame_where)
        w = check_positive_int(frame.get("width_px"), "width_px", frame_where)
        h = check_positive_int(frame.get("height_px"), "height_px", frame_where)
        if (w, h) != (stream_w, stream_h):
            raise ContractError(
                f"{frame_where}: 帧尺寸 {w}x{h} 与设备流配置 {stream_w}x{stream_h} 不一致（配置不匹配）"
            )
        frame_path = f"{base_dir}/{rel}"
        if frame_path not in entries:
            raise ContractError(f"{frame_where}: 帧文件 {frame_path} 不在包内（缺帧）")
        data = entries[frame_path]
        if fmt == "raw8" and len(data) != w * h:
            raise ContractError(
                f"{frame_path}: raw8 帧数据字节数 {len(data)} 与 {w}x{h}={w * h} 不一致"
            )
        check_ns_timestamp(frame.get("sensor_timestamp_ns"), "sensor_timestamp_ns", frame_where)
        check_ns_timestamp(frame.get("exposure_time_ns"), "exposure_time_ns", frame_where)
        check_timestamp_source(frame.get("timestamp_source"), "timestamp_source", frame_where)

    obs_ref = attempt.get("observations")
    if not isinstance(obs_ref, dict) or obs_ref.get("path") != "observations.json":
        raise ContractError(f"{where}: observations.path 必须是 'observations.json'（本 attempt 目录内）")
    obs_path = observations_json_path(patch_id, attempt_id)
    observations = _load_json(_require_entry(entries, obs_path), obs_path)
    _validate_observations(observations, obs_path)


def _validate_observations(observations: dict[str, Any], where: str) -> None:
    if not isinstance(observations, dict):
        raise ContractError(f"{where}: 根节点必须是对象")
    check_schema_version(observations.get("schema_version"), where)

    markers = observations.get("markers")
    if not isinstance(markers, list):
        raise ContractError(f"{where}: markers 必须是数组")
    for i, marker in enumerate(markers):
        marker_where = f"{where}: markers[{i}]"
        if not isinstance(marker, dict):
            raise ContractError(f"{marker_where}: 必须是对象")
        corners = marker.get("corners_image_px")
        if not isinstance(corners, list) or len(corners) != 4:
            raise ContractError(
                f"{marker_where}: corners_image_px 必须是 4 个二维角点（左上/右上/右下/左下，图像系，像素）"
            )
        for c, corner in enumerate(corners):
            _check_vector2(corner, f"{marker_where}: corners_image_px[{c}]")

    imu = observations.get("imu")
    if imu is not None:
        if not isinstance(imu, dict):
            raise ContractError(f"{where}: imu 必须是对象")
        segments = imu.get("segments")
        if not isinstance(segments, list):
            raise ContractError(f"{where}: imu.segments 必须是数组")
        for i, seg in enumerate(segments):
            seg_where = f"{where}: imu.segments[{i}]"
            if not isinstance(seg, dict):
                raise ContractError(f"{seg_where}: 必须是对象")
            check_ns_timestamp(seg.get("t_start_ns"), "t_start_ns", seg_where)
            check_ns_timestamp(seg.get("t_end_ns"), "t_end_ns", seg_where)

    pose = observations.get("preliminary_pose")
    if pose is not None:
        if not isinstance(pose, dict):
            raise ContractError(f"{where}: preliminary_pose 必须是对象")
        transform = pose.get("T_L_C")
        if transform is not None:
            parsed = Transform.from_mapping(transform, f"{where}: preliminary_pose.T_L_C")
            if parsed.from_frame != "L" or parsed.to_frame != "C":
                raise ContractError(
                    f"{where}: preliminary_pose.T_L_C 的 from_frame/to_frame 必须分别是 'L'/'C'"
                )


def _validate_session_completion(session: dict[str, Any], attempts: list[dict[str, Any]]) -> None:
    if session.get("capture_status") != "complete":
        return
    for attempt in attempts:
        status = attempt.get("capture_status")
        if status != "complete":
            raise ContractError(
                f"{attempt['_path']}: 会话标记 complete，但该尝试状态为 {status!r}；"
                "未完整落盘的组不得标为 complete（实施方案 §8.3）"
            )


def _check_no_stray_patch_files(
    session: dict[str, Any], entries: dict[str, bytes], known_attempt_paths: set[str]
) -> None:
    for entry in session["files"]:
        path = entry["path"]
        if not path.startswith(_PATCHES_PREFIX):
            continue
        if not _ATTEMPT_FILE_PATTERN.match(path):
            raise ContractError(
                f"{path}: patches/ 下的路径必须是 attempt.json、observations.json 或 frames/<文件>；"
                "存在无法归属任何 attempt 的文件"
            )
    for aj_path in known_attempt_paths:
        if aj_path not in entries:
            raise ContractError(f"{aj_path}: 会话登记的 attempt 缺少 attempt.json（缺帧/缺文件）")


def _check_vector3(value: object, where: str) -> None:
    if not isinstance(value, list) or len(value) != 3:
        raise ContractError(
            f"{where}: 变换维度错误——必须是 3 个数值分量，"
            f"实际为 {len(value) if isinstance(value, list) else '非数组'} 个"
        )
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ContractError(f"{where}[{i}]: 分量必须是数值，实际为 {type(v).__name__}")


def _check_vector2(value: object, where: str) -> None:
    if not isinstance(value, list) or len(value) != 2:
        raise ContractError(f"{where}: 必须是 [x, y] 两个数值（图像坐标，像素）")
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ContractError(f"{where}[{i}]: 分量必须是数值，实际为 {type(v).__name__}")
