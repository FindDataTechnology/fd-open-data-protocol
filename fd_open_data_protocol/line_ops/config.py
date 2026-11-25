"""环境驱动的线配置（共享实现，前缀参数化）。

五个 ops-mcp 仓的 `config.py` 除前缀与默认 base_url 外逐行相同：

    base_url=(env.get("WIRE_OPS_BASE_URL") or cls.base_url).rstrip("/")
    timeout_seconds=float(env.get("WIRE_OPS_TIMEOUT_SECONDS") or 20.0)
    auth_cache_ttl_seconds=float(env.get("WIRE_OPS_AUTH_CACHE_TTL") or 60.0)

本模块把「前缀 + 默认 base_url」参数化，其余不变。各仓仍可用自己的类名与
`from_env()`，只需 `make_settings_class()` 一次。
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LineSettings:
    """一条线的上游配置。字段名与五仓现状一致，便于平滑迁移。"""

    base_url: str
    timeout_seconds: float = 20.0
    auth_cache_ttl_seconds: float = 60.0

    @classmethod
    def from_env(cls, env=None) -> "LineSettings":
        raise NotImplementedError(
            "LineSettings 是基类形态；请用 make_settings_class() 生成带前缀的子类")


def make_settings_class(env_prefix: str, default_base_url: str):
    """生成一个带环境前缀的 Settings 类（与各仓既有 `Settings` 同形）。

    :param env_prefix: 环境变量前缀，如 `"WIRE_OPS"`（读 `WIRE_OPS_BASE_URL` 等）
    :param default_base_url: 三个环境变量都没设时的上游地址

    返回的类是 dataclass(frozen)，`from_env()` 可注入 `env`（测试用）。
    """
    _class_name = f"{env_prefix.title().replace('_', '')}Settings"

    @dataclass(frozen=True)
    class _Settings:
        base_url: str = default_base_url
        timeout_seconds: float = 20.0
        auth_cache_ttl_seconds: float = 60.0

        @classmethod
        def from_env(cls, env=None) -> "_Settings":
            env = env if env is not None else os.environ
            return cls(
                base_url=(env.get(f"{env_prefix}_BASE_URL") or cls.base_url).rstrip("/"),
                timeout_seconds=float(env.get(f"{env_prefix}_TIMEOUT_SECONDS") or 20.0),
                auth_cache_ttl_seconds=float(env.get(f"{env_prefix}_AUTH_CACHE_TTL") or 60.0),
            )

    _Settings.__name__ = _class_name
    _Settings.__qualname__ = _class_name
    return _Settings
