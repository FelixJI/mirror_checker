"""合成会话包生成器。

用于在没有任何真机数据时提供“明确标注为合成”的范例数据
（实施方案 §10.3 PR-01：没有真机数据时使用明确标注的合成包）。
所有内容都是确定性的：相同版本的生成器对相同常量产生字节级稳定的
会话包，便于两端（Python / Kotlin）共用同一份范例并做回归。

生成的包带有 ``provenance == "synthetic"``，各文件内也显式标注；
它不携带任何真实镜面测量结论（PR-01 边界）。
"""

from __future__ import annotations

import calendar
import io
import json
import math
import zipfile
from pathlib import Path

from .canonical import canonical_sha256, hash_object_excluding, sha256_hex
from .contracts import SCHEMA_VERSION, attempt_json_path, observations_json_path

SESSION_ID = "5f2c1a4e-8b3d-4c6a-9e0f-1a2b3c4d5e6f"
DEVICE_ID = "synthetic-tablet-01"
CALIBRATION_ID = "cal-synthetic-0001"
LAYOUT_ID = "layout-synthetic-A"
RECIPE_ID = "recipe-diag-lowfreq-v1"
PATCH_ID = "P0001"
ATTEMPT_ID = "A001"
CREATED_UTC = "2026-11-21T08:00:00Z"
#: 2026-11-21T08:00:00Z 的纳秒表示（十进制整数，写入 JSON 时转字符串）。
_BASE_EPOCH_S = calendar.timegm((2026, 11, 21, 8, 0, 0))
BASE_TIMESTAMP_NS = _BASE_EPOCH_S * 1_000_000_000

FRAME_W = 64
FRAME_H = 48
DIRECTIONS = (0, 90)
FREQUENCIES = (4, 8)
PHASE_STEPS = 4
EXPOSURE_NS = 5_000_000
FRAME_GAP_NS = 40_000_000

UNIT_CONVENTIONS = {
    "units": {"length": "m", "angle": "rad", "time": "s"},
    "coordinate_conventions": {
        "transform": "T_A_B",
        "image_coordinates": (
            "图像坐标：原点在左上角像素的左上角，x 向右、y 向下，单位像素；角点为亚像素浮点。"
        ),
        "screen_coordinates": (
            "屏幕对应坐标：u、v 为有效发光矩形内的归一化坐标 [0,1]，u 向右、v 向下，"
            "按 device.json 记录的显示方向解释。"
        ),
        "mirror_frame": (
            "镜面参考系 M：右手系，原点在镜面参考点，x 向右、y 向上、z 指向观察者。"
        ),
    },
}


def _json_bytes(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8") + b"\n"


def _patterns() -> list[dict]:
    patterns: list[dict] = []
    order = 1
    for direction in DIRECTIONS:
        for frequency in FREQUENCIES:
            for step in range(PHASE_STEPS):
                patterns.append(
                    {
                        "pattern_id": f"fringe-d{direction}-f{frequency}-p{step}",
                        "kind": "fringe",
                        "direction_deg": direction,
                        "frequency_cycles_per_pattern": frequency,
                        "phase_shift_rad": round(2.0 * math.pi * step / PHASE_STEPS, 6),
                        "display_order": order,
                    }
                )
                order += 1
    patterns.append({"pattern_id": "mask", "kind": "mask", "display_order": order})
    order += 1
    patterns.append({"pattern_id": "gray-127", "kind": "gray", "level": 127, "display_order": order})
    return patterns


def _frame_bytes(pattern: dict) -> bytes:
    """按图案参数确定性生成 8 位亮度帧。"""
    w, h = FRAME_W, FRAME_H
    kind = pattern["kind"]
    if kind == "fringe":
        theta = math.radians(pattern["direction_deg"])
        cycles = pattern["frequency_cycles_per_pattern"]
        phase = pattern["phase_shift_rad"]
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        pixels = bytearray(w * h)
        for y in range(h):
            for x in range(w):
                coordinate = (x * cos_t + y * sin_t) / w
                value = 128 + 100 * math.cos(2 * math.pi * cycles * coordinate + phase)
                pixels[y * w + x] = max(0, min(255, round(value)))
        return bytes(pixels)
    if kind == "mask":
        cx, cy, rx, ry = w / 2, h / 2, w * 0.375, h * 0.375
        pixels = bytearray(w * h)
        for y in range(h):
            for x in range(w):
                inside = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0
                pixels[y * w + x] = 255 if inside else 0
        return bytes(pixels)
    if kind == "gray":
        level = pattern["level"]
        return bytes([level]) * (w * h)
    raise ValueError(f"合成帧不支持图案类型 {kind}")


def _device_config() -> dict:
    return {
        "camera_id": "0",
        "stream_format": "YUV_420_888",
        "stream_width_px": FRAME_W,
        "stream_height_px": FRAME_H,
        "stream_fps": 30,
        "exposure_time_ns": str(EXPOSURE_NS),
        "sensor_sensitivity_iso": 100,
        "display_brightness": 128,
    }


def build_session_files() -> list[tuple[str, bytes]]:
    """构造合成会话的 (路径, 字节) 列表（不含 session.json，返回顺序确定）。"""
    files: list[tuple[str, bytes]] = []

    device_config = _device_config()
    device_config_hash = canonical_sha256(device_config)
    device = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "device_id": DEVICE_ID,
        "model": "synthetic reference tablet",
        "android": {"version_release": "unknown", "sdk_int": None},
        "camera": {
            "camera_id": "0",
            "facing": "front",
            "hardware_level": "unknown",
            "control_class": "uncontrolled",
            "stream": {"format": "YUV_420_888", "width_px": FRAME_W, "height_px": FRAME_H, "fps": 30},
        },
        "display": {
            "surface_width_px": 1280,
            "surface_height_px": 800,
            "rotation_at_capture": 0,
            "natural_orientation": "landscape",
            "effective_luminous": {"width_m": 0.2, "height_m": 0.135},
        },
        "sensors": {"gyroscope": True, "accelerometer": True},
        "device_config": device_config,
        "device_config_hash": device_config_hash,
    }
    files.append(("device.json", _json_bytes(device)))

    patterns = _patterns()

    calibration_intrinsics = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "status": "synthetic",
        "K": [[600.0, 0.0, 32.0], [0.0, 600.0, 24.0], [0.0, 0.0, 1.0]],
        "distortion": None,
    }
    calibration_screen = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "status": "synthetic",
        "effective_luminous_width_m": 0.2,
        "effective_luminous_height_m": 0.135,
        "surface_width_px": 1280,
        "surface_height_px": 800,
    }
    calibration_response = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "status": "synthetic",
        "gray_levels": None,
        "note": "合成数据：响应曲线未标定",
    }
    calibration_timing = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "status": "synthetic",
        "settle_display_frames": 3,
        "note": "合成数据：显示-曝光时序未实测",
    }
    files.append(("calibration/camera_intrinsics.json", _json_bytes(calibration_intrinsics)))
    files.append(("calibration/screen_mapping.json", _json_bytes(calibration_screen)))
    files.append(("calibration/response.json", _json_bytes(calibration_response)))
    files.append(("calibration/timing.json", _json_bytes(calibration_timing)))
    calibration_index = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "calibration_id": CALIBRATION_ID,
        "created_utc": CREATED_UTC,
        "items": [
            {"kind": "camera_intrinsics", "status": "synthetic", "file": "camera_intrinsics.json"},
            {"kind": "screen_mapping", "status": "synthetic", "file": "screen_mapping.json"},
            {"kind": "gray_response", "status": "synthetic", "file": "response.json"},
            {"kind": "display_exposure_timing", "status": "synthetic", "file": "timing.json"},
        ],
        "applicable_conditions": {
            "device_config_hash": device_config_hash,
            "notes": "合成标定：仅用于契约与管线回归，不用于定量结论",
        },
    }
    files.append(("calibration/index.json", _json_bytes(calibration_index)))

    def marker(strip_x: float, tag_id: int, center_y: float) -> dict:
        s = 0.015  # 半边长 15 mm -> 边长 30 mm
        corners = [
            [strip_x - s, center_y + s, 0.0],
            [strip_x + s, center_y + s, 0.0],
            [strip_x + s, center_y - s, 0.0],
            [strip_x - s, center_y - s, 0.0],
        ]
        return {
            "tag_id": tag_id,
            "corners_layout_m": corners,
            "side_length_m": {
                "measured": {
                    "value": 0.03,
                    "tool": "钢直尺（合成示例）",
                    "resolution_m": 0.0005,
                    "error_estimate_m": 0.001,
                }
            },
        }

    layout = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "layout_id": LAYOUT_ID,
        "marker_family": {
            "detector": "apriltag",
            "family": "tag36h11",
            "boundary": "检测器定义的标记边界（黑白交界），白色留白不计入边长",
        },
        "layout_frame": {
            "description": "布局系 L：右手系，原点在双条中点、条带平面上；x 向右、y 向上、z 沿法线指向相机侧"
        },
        "strips": [
            {
                "strip_id": "left",
                "markers": [marker(-0.1, 1 + i, 0.05 + 0.06 * i) for i in range(3)],
            },
            {
                "strip_id": "right",
                "markers": [marker(0.1, 11 + i, 0.05 + 0.06 * i) for i in range(3)],
            },
        ],
        "strip_relations": {
            "center_separation_m": {
                "measured": {"value": 0.2, "tool": "钢直尺（合成示例）", "error_estimate_m": 0.001}
            },
            "longitudinal_origin_offset_m": "unknown",
            "relative_tilt": "unknown",
            "coplanar_assumption": "unknown",
        },
        "mirror_reference": {
            "T_M_L": {
                "from_frame": "L",
                "to_frame": "M",
                "convention": "T_A_B",
                "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "translation_m": [0.0, 0.0, 0.01],
            },
            "method": "登记的实测关系（合成示例：假设条带平面在玻璃前表面前方 10 mm）",
            "glass_thickness": "unknown",
            "uncertainty": "unknown",
        },
        "installation": {
            "installed_utc": CREATED_UTC,
            "operator": "synthetic-generator",
            "photos": [],
        },
    }
    files.append(("layout.json", _json_bytes(layout)))

    recipe = {
        "schema_version": SCHEMA_VERSION,
        "provenance": "synthetic",
        "recipe_id": RECIPE_ID,
        "recipe_version": 1,
        "patterns": patterns,
        "display": {
            "region_normalized": {"u0": 0.0, "v0": 0.0, "u1": 1.0, "v1": 1.0},
            "background_level": 0,
            "amplitude_level": 255,
            "brightness_setting": 128,
        },
        "camera": {"exposure_time_ns": str(EXPOSURE_NS), "sensor_sensitivity_iso": 100, "ae_locked": True},
        "wait_strategy": {
            "settle_display_frames": 3,
            "min_gap_ns": str(2 * FRAME_GAP_NS),
            "timeout_ns": "30000000000",
        },
        "repeats": 1,
        "quality_gates": {"require_complete_frame_sequence": True},
        "applicable_calibration_id": CALIBRATION_ID,
        "applicable_device_config_hash": device_config_hash,
    }
    recipe["recipe_hash"] = hash_object_excluding(recipe, "recipe_hash")
    files.append(("recipe.json", _json_bytes(recipe)))

    expected_frames = [p["pattern_id"] for p in sorted(patterns, key=lambda p: p["display_order"])]
    frame_records = []
    base_dir = f"patches/{PATCH_ID}/attempts/{ATTEMPT_ID}"
    for i, pattern in enumerate(sorted(patterns, key=lambda p: p["display_order"])):
        name = f"frames/{i:04d}.bin"
        data = _frame_bytes(pattern)
        files.append((f"{base_dir}/{name}", data))
        frame_records.append(
            {
                "frame_index": i,
                "pattern_id": pattern["pattern_id"],
                "file": name,
                "format": "raw8",
                "width_px": FRAME_W,
                "height_px": FRAME_H,
                "sensor_timestamp_ns": str(BASE_TIMESTAMP_NS + i * FRAME_GAP_NS),
                "exposure_time_ns": str(EXPOSURE_NS),
                "timestamp_source": "REALTIME",
                "capture_result": {"sensor_sensitivity_iso": 100, "ae_state": "LOCKED"},
            }
        )

    observations = {
        "schema_version": SCHEMA_VERSION,
        "markers": [
            {
                "tag_id": 1,
                "valid": True,
                "corners_image_px": [[14.0, 10.0], [24.0, 10.0], [24.0, 20.0], [14.0, 20.0]],
                "edge_length_px": {"mean": 10.0},
                "border_distance_px": 10.0,
            },
            {
                "tag_id": 11,
                "valid": True,
                "corners_image_px": [[40.0, 10.0], [50.0, 10.0], [50.0, 20.0], [40.0, 20.0]],
                "edge_length_px": {"mean": 10.0},
                "border_distance_px": 10.0,
            },
        ],
        "imu": {
            "segments": [
                {
                    "t_start_ns": str(BASE_TIMESTAMP_NS),
                    "t_end_ns": str(BASE_TIMESTAMP_NS + len(frame_records) * FRAME_GAP_NS),
                    "gyro_radps": [0.0, 0.0, 0.0],
                    "accel_mps2": [0.0, 0.0, 9.81],
                }
            ]
        },
        "preliminary_pose": {
            "T_L_C": {
                "from_frame": "L",
                "to_frame": "C",
                "convention": "T_A_B",
                "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "translation_m": [0.0, 0.0, 0.5],
            },
            "method": "tag_pnp",
            "reprojection_error_px": 0.25,
            "assumptions": ["标记共面假设（布局系）"],
            "valid": True,
        },
        "stationarity": {"status": "pass", "max_corner_motion_px": 0.3},
    }
    files.append((observations_json_path(PATCH_ID, ATTEMPT_ID), _json_bytes(observations)))

    attempt = {
        "schema_version": SCHEMA_VERSION,
        "patch_id": PATCH_ID,
        "attempt_id": ATTEMPT_ID,
        "capture_status": "complete",
        "recipe_hash": recipe["recipe_hash"],
        "calibration_id": CALIBRATION_ID,
        "device_config_hash": device_config_hash,
        "started_utc": CREATED_UTC,
        "expected_frames": expected_frames,
        "frames": frame_records,
        "observations": {"path": "observations.json"},
    }
    files.append((attempt_json_path(PATCH_ID, ATTEMPT_ID), _json_bytes(attempt)))

    experiment = {
        "schema_version": SCHEMA_VERSION,
        "operator": "synthetic-generator",
        "entries": [
            {
                "time_utc": CREATED_UTC,
                "kind": "setup",
                "note": "合成会话：仅用于契约校验与双端回归，不含真实镜面测量",
            },
            {
                "time_utc": CREATED_UTC,
                "kind": "distance_check",
                "note": "合成示例：工作距离 0.5 m（未实测）",
            },
        ],
    }
    files.append(("experiment.json", _json_bytes(experiment)))
    return files


def build_session() -> dict:
    """构造完整的 session.json 内容。"""
    body = build_session_files()
    manifest = [
        {"path": path, "sha256": sha256_hex(data), "size_bytes": len(data)} for path, data in body
    ]
    session = {
        "schema_version": SCHEMA_VERSION,
        "package_kind": "capture_session",
        "session_id": SESSION_ID,
        "created_utc": CREATED_UTC,
        "provenance": "synthetic",
        "device": {"device_id": DEVICE_ID, "config_hash": None, "path": "device.json"},
        "calibration": {"present": True, "calibration_id": CALIBRATION_ID, "path": "calibration/index.json"},
        "layout": {"layout_id": LAYOUT_ID, "path": "layout.json"},
        "recipe": {"recipe_id": RECIPE_ID, "recipe_hash": None, "path": "recipe.json"},
        "capture_status": "complete",
        "transfer_status": "local_only",
        **UNIT_CONVENTIONS,
        "patches": [
            {
                "patch_id": PATCH_ID,
                "attempts": [
                    {
                        "attempt_id": ATTEMPT_ID,
                        "path": attempt_json_path(PATCH_ID, ATTEMPT_ID),
                        "capture_status": "complete",
                    }
                ],
            }
        ],
        "files": manifest,
    }
    # 回填引用哈希
    device = json.loads(dict(body)["device.json"])
    recipe = json.loads(dict(body)["recipe.json"])
    session["device"]["config_hash"] = device["device_config_hash"]
    session["recipe"]["recipe_hash"] = recipe["recipe_hash"]
    return session


def write_sample_session(path: str | Path) -> Path:
    """生成合成会话 ZIP 并返回其路径。

    所有条目使用固定的时间戳与压缩方式，保证同一生成器版本输出
    字节级稳定（便于双端共用同一范例并做回归比对）。
    """
    path = Path(path)
    body = build_session_files()
    session = build_session()

    def _info(arcname: str) -> zipfile.ZipInfo:
        # ZIP_STORED（无压缩）保证跨平台字节级稳定：不同 zlib 版本的
        # deflate 输出可能不同，而契约回归需要“同一生成器版本 → 同一字节”。
        info = zipfile.ZipInfo(arcname, date_time=(2026, 11, 21, 8, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o644 << 16
        return info

    with zipfile.ZipFile(path, "w") as zf:
        for arcname, data in body:
            zf.writestr(_info(arcname), data)
        zf.writestr(_info("session.json"), _json_bytes(session))
    return path
