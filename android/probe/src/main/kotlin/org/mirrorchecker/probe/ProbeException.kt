package org.mirrorchecker.probe

/**
 * 探测/诊断数据问题（能力缺失、配置失效、试开失败等）。
 *
 * 与契约层的 [org.mirrorchecker.contracts.ContractException] 分开：
 * 会话契约违规表示数据不满足协议；[ProbeException] 表示探测得到的
 * 硬件/显示状态不满足采集前提（实施方案 §5.1、§3.3）。
 * 消息同样以「对象: 字段」开头，便于定位。
 */
class ProbeException(message: String) : RuntimeException(message)
