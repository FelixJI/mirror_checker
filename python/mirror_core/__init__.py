"""mirror_core：镜面检测的契约与光学核心库（不依赖 Web UI）。

PR-01 交付内容契约（会话包解析与校验、坐标变换、规范哈希）与
合成会话生成器。光学解算、融合与成像评价在后续 PR 中加入，
接口遵循 docs/plans 中的实施方案。
"""

from .contracts import (
    CAPTURE_STATUSES,
    JOB_STATUSES,
    PROVENANCES,
    SCHEMA_VERSION,
    SUPPORT_STATUSES,
    TRANSFER_STATUSES,
    ContractError,
)
from .transforms import Transform

__all__ = [
    "CAPTURE_STATUSES",
    "JOB_STATUSES",
    "PROVENANCES",
    "SCHEMA_VERSION",
    "SUPPORT_STATUSES",
    "TRANSFER_STATUSES",
    "ContractError",
    "Transform",
]
