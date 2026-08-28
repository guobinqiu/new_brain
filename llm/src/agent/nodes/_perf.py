"""Node-level performance logging cross-cutting concern.

All graph node functions share the signature `async def(state: dict) -> dict`,
which makes them perfect for a decorator-based aspect.

Two ways to use this:

1. Explicit decorator (uncommon — prefer option 2):

       @perf_node("validate")
       async def validate_node(state): ...

2. At graph build time (recommended — zero per-node boilerplate):

       builder.add_node(NodeName.VALIDATE, wrap_node("validate", validate_node))

   or via the sugar helper `add_perf_node(builder, NodeName.VALIDATE,
   validate_node)`.

Emits a single log line per node execution:
    phase=perf kind=node label=<name> total_ms=... ok=True|False

Idempotent: wrapping an already-wrapped function is a no-op, so it's safe to
combine both styles without double-counting.
"""

from __future__ import annotations

import time as _time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from llm.src.infra.logger import get_logger, log_perf

# Module-level logger keeps the "log_t" field consistent across all nodes.
_logger = get_logger("agent.node.perf")
_state_logger = get_logger("agent.node.state")

# Marker attribute used to detect already-wrapped callables, so we never
# double-wrap (which would produce two perf log lines per node execution).
_WRAPPED_MARK = "__perf_node_wrapped__"

NodeFn = Callable[[dict], Awaitable[dict]]

# State fields to track for transition logging.
# CS 字段（phase/intent/slot/fired_triggers/...）已删除（架构 §13.1）。
_TRACKED_FIELDS = (
    "tool_results",
    "llm_ms",
    "tokens_in",
    "tokens_out",
    "cost",
)


def _merge_state(before: dict, patch: dict) -> dict:
    """Apply patch on top of before to get the merged state snapshot."""
    merged = {}
    for key in _TRACKED_FIELDS:
        if key in patch:
            merged[key] = patch[key]
        elif key in before:
            merged[key] = before[key]
    return merged


def _log_state_snapshot(label: str, merged: dict) -> None:
    """Log a full state snapshot after node execution.

    Only the fields AgentState actually defines are emitted
    （tool_results / llm_ms / tokens_in/out / cost — 见 AgentState），
    旧的 CS 字段（phase / current_intent / collected_slots / current_slot /
    fired_triggers / injected_slots / pending_triggers / last_error /
    retry_count）已从 schema 移除，此处仅打印存在的值。
    """
    snapshot: dict[str, Any] = {
        k: merged[k] for k in _TRACKED_FIELDS if k in merged and merged[k] not in (None, [], {}, 0, 0.0)
    }
    _state_logger.info("state snapshot", node=label, **snapshot)


def _log_state_transition(label: str, before: dict, patch: dict) -> None:
    """Log state changes produced by a node.

    Only logs tracked fields that actually changed. Skips nodes that return
    an empty patch or no tracked-field changes (e.g. router).
    """
    if not patch:
        return

    changes: dict[str, Any] = {}
    for key in _TRACKED_FIELDS:
        if key not in patch:
            continue
        old = before.get(key)
        new = patch[key]
        # 跳过值未变（避免冗余 diff）
        if old == new:
            continue
        changes[key] = {"old": old, "new": new}

    if not changes:
        return

    # Build a concise summary for quick scanning
    summary_parts: list[str] = []
    if "tool_results" in changes:
        summary_parts.append("tool_results updated")
    if "llm_ms" in changes:
        summary_parts.append(f"llm_ms={changes['llm_ms']['new']}")
    if "tokens_in" in changes or "tokens_out" in changes:
        ti = changes.get("tokens_in", {}).get("new", 0) or 0
        to = changes.get("tokens_out", {}).get("new", 0) or 0
        summary_parts.append(f"tokens={ti}+{to}")
    if "cost" in changes:
        summary_parts.append(f"cost={changes['cost']['new']}")

    _state_logger.info(
        "state transition",
        node=label,
        summary=" | ".join(summary_parts) if summary_parts else "minor",
        changes=changes,
    )

    # Full snapshot follows the diff — no mental reconstruction needed
    merged = _merge_state(before, patch)
    _log_state_snapshot(label, merged)


def wrap_node(label: str, fn: NodeFn) -> NodeFn:
    """Wrap a node async function with a perf log line.

    Idempotent: if `fn` was already wrapped by this helper, returns `fn`
    unchanged.

    Args:
        label: logical node name used in the `label=` field of the perf log.
        fn: the node coroutine function.

    Returns:
        A wrapped coroutine function whose only side effect (beyond fn's own)
        is emitting one `kind="node"` perf log line per invocation.
    """
    if getattr(fn, _WRAPPED_MARK, False):
        return fn

    @wraps(fn)
    async def _wrapped(state: dict) -> dict:
        start = _time.perf_counter()
        ok = True
        try:
            patch = await fn(state)
            _log_state_transition(label, state, patch)
            return patch
        except Exception:
            ok = False
            raise
        finally:
            total_ms = (_time.perf_counter() - start) * 1000
            log_perf(
                _logger,
                "node done",
                kind="node",
                label=label,
                total_ms=round(total_ms, 1),
                ok=ok,
            )

    setattr(_wrapped, _WRAPPED_MARK, True)
    return _wrapped  # type: ignore[return-value]


def perf_node(label: str) -> Callable[[NodeFn], NodeFn]:
    """Decorator form of `wrap_node`.

    Example:

        @perf_node("intent")
        async def intent_node(state): ...
    """
    def _deco(fn: NodeFn) -> NodeFn:
        return wrap_node(label, fn)
    return _deco


def add_perf_node(builder: Any, name: str, fn: NodeFn) -> None:
    """Sugar for `builder.add_node(name, wrap_node(name, fn))`.

    Using the same string for both the graph node name and the perf label
    keeps logs grep-friendly.
    """
    builder.add_node(name, wrap_node(name, fn))
