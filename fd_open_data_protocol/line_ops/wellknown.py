"""线自描述端点 `/.well-known/line-manifest.json`（公开、免鉴权、零网络）。

为什么在鉴权门**之前**应答：平台/客户在未持有本线凭据时，也要能读到「这条线认哪些
钥匙」。放在门后会让未开通的客户连自描述都拿不到。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

WELL_KNOWN_PATH = "/.well-known/line-manifest.json"
LINE_MANIFEST_ENV = "LINE_MANIFEST_PATH"
#: 清单是运行期契约：改一次要生效，但不能让边缘缓存长期撒谎。
MANIFEST_CACHE_CONTROL = "public, max-age=300"


def manifest_candidates(anchor: Path | str | None = None) -> list[Path]:
    """按优先级列出可能放清单的位置（`LINE_MANIFEST_PATH` 一项即封顶）。

    为什么要链而不是一条：**pip 装进去的包与源码树的 `__file__` 不同**。镜像是
    console script 起的，`__file__` 落在 site-packages，`parents[1]` 根本不是仓根——
    清单就在 `/app/line-manifest.json` 却读不到（lex 线 2026-11-11 真机 404，
    源码运行验不出来）。所以源码树、CWD（镜像 WORKDIR）、与包同级三处依次找。

    :param anchor: 用来推导「仓根」的文件路径。**消费仓必须传自己的**
        （通常是该仓 `server.py` 的 `__file__`）：不传就用本模块的 `__file__`，
        那会指向 protocol 包自己的目录，算出来的仓根是错的（2026-11-25 实测：
        五个消费仓的 `manifest_path()` 全部指到 protocol 包里）。
    """
    override = os.environ.get(LINE_MANIFEST_ENV)
    if override:
        return [Path(override)]
    here = Path(anchor).resolve() if anchor is not None else Path(__file__).resolve()
    return [
        here.parents[1] / "line-manifest.json",  # 源码树 / 镜像里包与清单同根
        Path.cwd() / "line-manifest.json",       # pip 装的包：CWD 才是仓根
        here.parent / "line-manifest.json",      # 清单与包同级（兜底）
    ]


def manifest_path(anchor: Path | str | None = None) -> Path:
    """实际取用的清单路径；都不存在时返回首选位置（让 404 能点名期望路径）。"""
    candidates = manifest_candidates(anchor)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def manifest_response(anchor: Path | str | None = None) -> tuple[int, bytes, list[tuple[bytes, bytes]]]:
    """(status, body, extra_headers) —— 不读网络、不建会话。

    缺失=404（该线未发布清单，属配置事实）；存在但不可解析=500（属缺陷，不能
    伪装成 404 让调用方以为「本来就没有」）。
    """
    json_headers = [(b"content-type", b"application/json; charset=utf-8")]
    path = manifest_path(anchor)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return 404, b'{"detail":"line-manifest not published"}', json_headers
    except OSError as exc:
        return 500, json.dumps(
            {"detail": f"line-manifest unreadable: {type(exc).__name__}"}).encode(), json_headers
    try:
        json.loads(raw)
    except ValueError:
        return 500, b'{"detail":"line-manifest is not valid JSON"}', json_headers
    return 200, raw, json_headers + [
        (b"cache-control", MANIFEST_CACHE_CONTROL.encode()),
    ]
