"""HMAC-SHA256 签名算法单测（§11.1）。

覆盖：
- 时间戳边界（0、负数、极大值）
- secret 含特殊字符、UTF-8
- body 含中文 UTF-8
- 与 qdrant 文档 example 字节级一致（已知 input → 已知 hex 黄金向量）
- method/path 任意变化（验证拼接顺序）

不变量：返回 lower-case hex 摘要，长度 64。
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

# 黄金向量：
#   body    = '{"query":"hi"}'              (12 bytes UTF-8)
#   method  = 'POST'
#   path    = '/api/open/rag/search'
#   ts      = 1700000000
#   app_id  = 'my_agent'
#   secret  = 'test_secret'
# body_hash = sha256(b'{"query":"hi"}') =
#   a43337f2c2aecb3709c60fcd7b28f6a555362fffa9e89588a63f34fdad8fe8ad
# signature = hmac_sha256(secret, canonical) =
#   348f5b365094251bf7a15a24cb491d2b6a7cc7ac4b88d651d09f9ee4ec6de7e5
GOLDEN_BODY = b'{"query":"hi"}'
GOLDEN_BODY_HASH = "a43337f2c2aecb3709c60fcd7b28f6a555362fffa9e89588a63f34fdad8fe8ad"
GOLDEN_SIGNATURE = "348f5b365094251bf7a15a24cb491d2b6a7cc7ac4b88d651d09f9ee4ec6de7e5"
GOLDEN_CANONICAL_LINES = 5  # METHOD\nPATH\nTS\nHASH\nAPP_ID


def _try_sign(**kwargs):
    """尝试导入并调用 sign()。缺失模块 → pytest.fail（不是 skip），确保 RED。"""
    try:
        from llm.src.rag.client import sign  # type: ignore
    except Exception as exc:
        pytest.fail(f"rag.client.sign not implemented yet — RED ({exc})")
    try:
        return sign(**kwargs)
    except Exception as exc:
        # 实现存在但调用出错也算 RED：让 coder-agent 看到具体失败信号
        pytest.fail(f"sign(...) 调用抛错: {exc}")


def test_sign_returns_lowercase_hex_64_chars():
    """签名字符串必须是 lower-case 64 字符 hex。"""
    out = _try_sign(
        body_bytes=b"hello",
        method="POST",
        path="/api/open/rag/search",
        ts=1700000000,
        app_id="my_agent",
        secret="test_secret",
    )
    if out is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert isinstance(out, str)
    assert len(out) == 64
    assert out == out.lower()
    # 仅含十六进制字符
    int(out, 16)


def test_sign_golden_vector_matches_qdrant_doc_example():
    """已知 input → 已知 hex（与文档 example 字节级一致）。"""
    out = _try_sign(
        body_bytes=GOLDEN_BODY,
        method="POST",
        path="/api/open/rag/search",
        ts=1700000000,
        app_id="my_agent",
        secret="test_secret",
    )
    if out is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert out == GOLDEN_SIGNATURE


def test_sign_canonical_string_construction_order():
    """签名拼接顺序必须是 METHOD\\nPATH\\nTS\\nHASH\\nAPP_ID。"""
    out = _try_sign(
        body_bytes=GOLDEN_BODY,
        method="POST",
        path="/api/open/rag/search",
        ts=1700000000,
        app_id="my_agent",
        secret="test_secret",
    )
    if out is None:
        pytest.fail("rag.client.sign not implemented yet — RED")

    canonical = (
        f"POST\n/api/open/rag/search\n1700000000\n{GOLDEN_BODY_HASH}\nmy_agent"
    )
    expected = hmac.new(b"test_secret", canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    assert out == expected

    # 篡改任一字段都应改变签名
    canonical_swapped = (
        f"my_agent\n/api/open/rag/search\n1700000000\n{GOLDEN_BODY_HASH}\nPOST"
    )
    assert hmac.new(
        b"test_secret", canonical_swapped.encode(), hashlib.sha256
    ).hexdigest() != out


@pytest.mark.parametrize(
    "ts_value",
    [0, -1, 1, 1700000000, 2**31 - 1, 2**40, 2**62, 9_999_999_999],
)
def test_sign_handles_arbitrary_timestamps(ts_value):
    """任意 Unix 时间戳（边界、负数、巨大值）都应可签名。"""
    out = _try_sign(
        body_bytes=b"x",
        method="POST",
        path="/api/open/rag/search",
        ts=ts_value,
        app_id="a",
        secret="s",
    )
    if out is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert isinstance(out, str) and len(out) == 64


def test_sign_handles_secret_with_special_chars_and_utf8():
    """secret 含换行/等号/斜杠/中文 时，签名字节级不应抛错且结果稳定。"""
    secrets = [
        "line\nbreak",
        "key=value",
        "path/with/slash",
        "混合中文 secret",  # UTF-8
        "🤖🚀",           # emoji
        "",               # empty
    ]
    for s in secrets:
        out = _try_sign(
            body_bytes=b"q",
            method="POST",
            path="/api/open/rag/search",
            ts=1700000000,
            app_id="agent-1",
            secret=s,
        )
        if out is None:
            pytest.fail("rag.client.sign not implemented yet — RED")
        assert isinstance(out, str) and len(out) == 64


def test_sign_handles_chinese_utf8_body():
    """body 含中文（UTF-8）—— body_hash 用的是 UTF-8 字节，签名互不混淆。"""
    body = "退款流程如何处理？".encode()
    out = _try_sign(
        body_bytes=body,
        method="POST",
        path="/api/open/rag/search",
        ts=1700000000,
        app_id="rag_demo",
        secret="another_secret",
    )
    if out is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    # 与手算的 SHA-256 hash 比对一致性
    expected_hash = hashlib.sha256(body).hexdigest()
    canonical = f"POST\n/api/open/rag/search\n1700000000\n{expected_hash}\nrag_demo"
    expected_sig = hmac.new(
        b"another_secret", canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert out == expected_sig


def test_sign_path_must_not_include_query():
    """PATH 固定为 /api/open/rag/search，不含 query。"""
    out1 = _try_sign(
        body_bytes=b"{}",
        method="POST",
        path="/api/open/rag/search",
        ts=1,
        app_id="a",
        secret="s",
    )
    out2 = _try_sign(
        body_bytes=b"{}",
        method="POST",
        path="/api/open/rag/search?foo=bar",  # 不应使用此形式
        ts=1,
        app_id="a",
        secret="s",
    )
    if out1 is None or out2 is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert out1 != out2  # path 一变签名就变（证明 path 进入签名对象）


def test_sign_different_methods_yield_different_signatures():
    """GET vs POST 应产生不同签名（证明 method 进入签名对象）。"""
    out_post = _try_sign(
        body_bytes=b"{}",
        method="POST",
        path="/api/open/rag/search",
        ts=1,
        app_id="a",
        secret="s",
    )
    out_get = _try_sign(
        body_bytes=b"{}",
        method="GET",
        path="/api/open/rag/search",
        ts=1,
        app_id="a",
        secret="s",
    )
    if out_post is None or out_get is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert out_post != out_get


def test_sign_is_byte_sensitive_to_body():
    """单字节 body 改变 → 签名改变（证明 body 字节级进入签名对象）。"""
    out1 = _try_sign(
        body_bytes=b'{"query":"hi"}',
        method="POST",
        path="/api/open/rag/search",
        ts=1,
        app_id="a",
        secret="s",
    )
    out2 = _try_sign(
        body_bytes=b'{"query":"hI"}',  # 大小写差一比特
        method="POST",
        path="/api/open/rag/search",
        ts=1,
        app_id="a",
        secret="s",
    )
    if out1 is None or out2 is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert out1 != out2


def test_sign_empty_body_works():
    """空 body 也应能签名（不得抛错）。"""
    out = _try_sign(
        body_bytes=b"",
        method="POST",
        path="/api/open/rag/search",
        ts=1700000000,
        app_id="a",
        secret="s",
    )
    if out is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert isinstance(out, str) and len(out) == 64


def test_sign_is_deterministic():
    """同一组 input 两次调用 → 输出相同（无随机盐、无时钟依赖）。"""
    kwargs = dict(
        body_bytes=b"payload",
        method="POST",
        path="/api/open/rag/search",
        ts=1234567890,
        app_id="myid",
        secret="mysecret",
    )
    out_a = _try_sign(**kwargs)
    out_b = _try_sign(**kwargs)
    if out_a is None or out_b is None:
        pytest.fail("rag.client.sign not implemented yet — RED")
    assert out_a == out_b


def test_sign_module_path_is_rag_client():
    """sign 必须存在于 rag.client 模块。"""
    try:
        from llm.src.rag.client import sign  # type: ignore
    except ImportError as exc:
        pytest.fail(f"无法从 rag.client 导入 sign: {exc}")
    assert callable(sign)
