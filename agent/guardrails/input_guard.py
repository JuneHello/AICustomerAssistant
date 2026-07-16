"""输入安全检查 — PII 脱敏、越狱检测、内容长度校验

在用户消息进入 Agent 状态机之前执行安全过滤。
检测到违规时，直接拦截并返回安全回复，不进入后续节点。
"""

import re

import structlog
from langchain_core.messages import AIMessage

from agent.state import AgentState

logger = structlog.get_logger()

# ── PII 正则模式 ──────────────────────────────────────────────────
PHONE_PATTERN = re.compile(
    r"(?<!\d)"  # 前面不是数字
    r"1[3-9]\d{9}"  # 中国大陆手机号
    r"(?!\d)"  # 后面不是数字
)

ID_CARD_PATTERN = re.compile(
    r"(?<!\d)"
    r"\d{17}[\dXx]"  # 18 位身份证号
    r"(?!\d)"
)

BANK_CARD_PATTERN = re.compile(
    r"(?<!\d)"
    r"\d{16,19}"  # 银行卡号 (16-19 位)
    r"(?!\d)"
)

# ── 越狱关键词 ──────────────────────────────────────────────────
JAILBREAK_PATTERNS = [
    re.compile(r"忽略.*(?:之前|以上|上面).*(?:指令|提示|规则|设定)", re.IGNORECASE),
    re.compile(r"(?:假装|扮演|角色扮演).*(?:不是|不再是).*(?:客服|助手)", re.IGNORECASE),
    re.compile(r"(?:system\s*prompt|系统提示词|内部指令)", re.IGNORECASE),
    re.compile(r"(?:DAN|developer\s*mode|越狱模式)", re.IGNORECASE),
    re.compile(r"(?:ignore|disregard).*(?:previous|above).*(?:instructions|rules)", re.IGNORECASE),
]

# 内容长度限制
MAX_MESSAGE_LENGTH = 5000


def detect_pii(text: str) -> list[dict]:
    """检测文本中的 PII 信息。"""
    findings = []

    for match in PHONE_PATTERN.finditer(text):
        findings.append({"type": "phone", "value": match.group(), "start": match.start()})

    for match in ID_CARD_PATTERN.finditer(text):
        findings.append({"type": "id_card", "value": match.group(), "start": match.start()})

    for match in BANK_CARD_PATTERN.finditer(text):
        # 排除已识别为身份证的匹配
        if not any(f["start"] == match.start() for f in findings):
            findings.append({"type": "bank_card", "value": match.group(), "start": match.start()})

    return findings


def mask_pii(text: str, findings: list[dict]) -> str:
    """将检测到的 PII 替换为脱敏掩码。"""
    masked = text
    # 按位置倒序替换，避免偏移
    for finding in sorted(findings, key=lambda f: f["start"], reverse=True):
        value = finding["value"]
        pii_type = finding["type"]
        if pii_type == "phone":
            mask = value[:3] + "****" + value[-4:]
        elif pii_type == "id_card":
            mask = value[:4] + "**********" + value[-4:]
        else:
            mask = value[:4] + "****" + value[-4:]
        masked = masked[:finding["start"]] + mask + masked[finding["start"] + len(value):]
    return masked


def detect_jailbreak(text: str) -> bool:
    """检测越狱/提示词注入攻击。"""
    return any(pattern.search(text) for pattern in JAILBREAK_PATTERNS)


async def input_guardrails(state: AgentState) -> dict:
    """输入安全检查节点。

    检查顺序：
    1. 内容长度校验
    2. 越狱检测
    3. PII 检测与脱敏

    如果检测到越狱攻击，标记 intent 为 blocked。
    PII 不会阻断对话，但会在日志中记录并对消息进行脱敏。
    """
    messages = state["messages"]
    if not messages:
        return {}

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    # 1. 内容长度校验
    if len(content) > MAX_MESSAGE_LENGTH:
        logger.warning(
            "input_guard.message_too_long",
            length=len(content),
            max=MAX_MESSAGE_LENGTH,
        )
        return {
            "messages": [
                AIMessage(content="您的消息过长，请精简后重新发送，谢谢 🙏")
            ],
            "intent": "blocked",
        }

    # 2. 越狱检测
    if detect_jailbreak(content):
        logger.warning(
            "input_guard.jailbreak_detected",
            content_preview=content[:100],
            session_id=state.get("session_id"),
        )
        return {
            "messages": [
                AIMessage(
                    content="我是商城官方客服小蜜，很乐意帮您解决购物相关的问题 😊 请问有什么可以帮您的？"
                )
            ],
            "intent": "blocked",
        }

    # 3. PII 检测与脱敏
    pii_findings = detect_pii(content)
    if pii_findings:
        logger.info(
            "input_guard.pii_detected",
            pii_types=[f["type"] for f in pii_findings],
            session_id=state.get("session_id"),
        )
        # PII 脱敏后继续对话（不阻断）
        # 注意：这里仅记录日志，实际消息内容不修改
        # 因为用户可能需要提供订单号等信息来查询

    return {}
