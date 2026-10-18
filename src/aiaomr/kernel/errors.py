"""错误码与严重级别。

依据：规格 §3.3 的表，以及 §7「只有阶段级与全局级才带退出码」。

级别只有三种：

- `STAGE`（阶段级）：这一段做不下去，整个运行停止，带退出码；
- `SYSTEM`（系统级）：只影响单个系统或单次调用，记录后继续，不带退出码；
- `GLOBAL`（全局级）：请求层或预算层的失败，整个运行停止，带退出码。

错误码与退出码都由规格固定，代码里不许另起字符串。
"""

from enum import Enum


class ErrorCode(str, Enum):
    E_INPUT_UNREADABLE = "E_INPUT_UNREADABLE"
    E_NO_SYSTEM = "E_NO_SYSTEM"
    E_TAB_STAFF_MISSING = "E_TAB_STAFF_MISSING"
    E_SKELETON_UNREAD = "E_SKELETON_UNREAD"
    E_VLM_HTTP = "E_VLM_HTTP"
    E_VLM_EMPTY = "E_VLM_EMPTY"
    E_VLM_SCHEMA = "E_VLM_SCHEMA"
    E_BUDGET_EXCEEDED = "E_BUDGET_EXCEEDED"
    E_BUILD_VALIDATE = "E_BUILD_VALIDATE"
    E_BUILD_ROUNDTRIP = "E_BUILD_ROUNDTRIP"
    E_AUDIT = "E_AUDIT"


class ErrorSeverity(str, Enum):
    STAGE = "stage"
    SYSTEM = "system"
    GLOBAL = "global"


# 规格 §3.3 的「级别」列，逐条对应。
ERROR_SEVERITY: dict[ErrorCode, ErrorSeverity] = {
    ErrorCode.E_INPUT_UNREADABLE: ErrorSeverity.STAGE,
    ErrorCode.E_NO_SYSTEM: ErrorSeverity.STAGE,
    ErrorCode.E_TAB_STAFF_MISSING: ErrorSeverity.SYSTEM,
    ErrorCode.E_SKELETON_UNREAD: ErrorSeverity.STAGE,
    ErrorCode.E_VLM_HTTP: ErrorSeverity.GLOBAL,
    ErrorCode.E_VLM_EMPTY: ErrorSeverity.SYSTEM,
    ErrorCode.E_VLM_SCHEMA: ErrorSeverity.SYSTEM,
    ErrorCode.E_BUDGET_EXCEEDED: ErrorSeverity.GLOBAL,
    ErrorCode.E_BUILD_VALIDATE: ErrorSeverity.STAGE,
    ErrorCode.E_BUILD_ROUNDTRIP: ErrorSeverity.STAGE,
    ErrorCode.E_AUDIT: ErrorSeverity.STAGE,
}

# 规格 §3.3 的「退出码」列。没有退出码的（"—"）是系统级错误，故意不登记：
# 系统级失败只记录、不中断（§7）。
ERROR_EXIT_CODE: dict[ErrorCode, int] = {
    ErrorCode.E_INPUT_UNREADABLE: 1,
    ErrorCode.E_NO_SYSTEM: 1,
    ErrorCode.E_SKELETON_UNREAD: 1,
    ErrorCode.E_VLM_HTTP: 2,
    ErrorCode.E_BUDGET_EXCEEDED: 3,
    ErrorCode.E_BUILD_VALIDATE: 2,
    ErrorCode.E_BUILD_ROUNDTRIP: 2,
    ErrorCode.E_AUDIT: 2,
}
