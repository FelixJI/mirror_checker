"""mirror_cli 入口。用法见 ``python -m mirror_cli --help``。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mirror_core.contracts import ContractError
from mirror_core.sample import write_sample_session
from mirror_core.session import SessionPackage


def _cmd_validate(args: argparse.Namespace) -> int:
    package = SessionPackage.open(args.session)
    summary = package.summary()
    print(f"契约校验通过: {args.session}")
    print(f"  schema_version: {summary['schema_version']}")
    print(f"  会话 ID: {summary['session_id']}")
    print(f"  来源: {summary['provenance']}")
    print(f"  采集状态: {summary['capture_status']} / 传输状态: {summary['transfer_status']}")
    print(
        f"  补丁/尝试: {summary['patches']}/{summary['attempts']}"
        f"，帧合计 {summary['frames']}"
    )
    print(f"  清单文件: {summary['manifest_files']} 个，SHA-256 与大小全部一致")
    return 0


def _cmd_make_sample(args: argparse.Namespace) -> int:
    output = Path(args.output)
    write_sample_session(output)
    # 生成的包必须能被同一套契约校验通过
    SessionPackage.open(output)
    print(f"合成会话已生成并通过契约校验: {output}")
    return 0


def _cmd_solve(args: argparse.Namespace) -> int:
    print(
        "solve 计划于 PR-07 交付（真实单站 SOFAST 适配）；PR-01 只提供 validate。",
        file=sys.stderr,
    )
    return 2


def _cmd_workbench(args: argparse.Namespace) -> int:
    print(
        "workbench 计划于 PR-08 交付（电脑工作台）；PR-01 只提供 validate。",
        file=sys.stderr,
    )
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mirror_cli",
        description="镜面检测：会话校验、求解与工作台命令行（接口约定见实施方案 §14）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="校验一个会话 ZIP 是否符合数据契约")
    p_validate.add_argument("session", help="会话包路径（ZIP）")
    p_validate.set_defaults(func=_cmd_validate)

    p_sample = sub.add_parser("make-sample", help="生成明确标注为合成的范例会话 ZIP")
    p_sample.add_argument("--output", required=True, help="输出 ZIP 路径")
    p_sample.set_defaults(func=_cmd_make_sample)

    p_solve = sub.add_parser("solve", help="求解会话（PR-07 交付）")
    p_solve.add_argument("session", help="会话包路径（ZIP）")
    p_solve.add_argument("--output", required=True, help="结果目录")
    p_solve.set_defaults(func=_cmd_solve)

    p_workbench = sub.add_parser("workbench", help="启动本地工作台（PR-08 交付）")
    p_workbench.add_argument("--host", default="127.0.0.1")
    p_workbench.add_argument("--port", type=int, default=8765)
    p_workbench.set_defaults(func=_cmd_workbench)

    return parser


def main(argv: list[str] | None = None) -> int:
    # 输出统一 UTF-8：Windows 非 UTF-8 控制台（如 cp1252/cp936）下，
    # 中文消息会触发 UnicodeEncodeError 或被 backslashreplace 转义。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - 非常规流
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ContractError as exc:
        print(f"契约校验失败: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"无法读取输入: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
