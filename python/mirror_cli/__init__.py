"""mirror_cli：校验、求解与工作台命令行入口。

命令接口遵循实施方案 §14 的约定：

    python -m mirror_cli validate SESSION.zip
    python -m mirror_cli solve SESSION.zip --output RESULT_DIR
    python -m mirror_cli workbench --host 127.0.0.1 --port 8765

PR-01 只实现 ``validate`` 与 ``make-sample``；``solve`` 计划于 PR-07、
``workbench`` 计划于 PR-08 交付，当前显式报错退出而不是静默失败。
"""
