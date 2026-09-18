"""CapCut 드래프트 읽기/쓰기.

`draft` 는 `pycapcut` 에 기대므로 여기서 미리 불러오지 않는다. 카드뉴스나
`doctor` 처럼 CapCut 을 안 쓰는 기능이 그것 때문에 죽으면 곤란하다.
실제로 쓸 때 처음 불러온다.
"""

from __future__ import annotations

import importlib

from . import paths
from .errors import TemplateError

__all__ = ["draft", "paths", "TemplateError"]


def __getattr__(name: str):
    if name == "draft":
        # `from . import draft` 를 쓰면 그 임포트가 다시 이 함수를 불러
        # 무한 재귀에 빠진다. importlib 로 하위 모듈을 직접 가져온다.
        return importlib.import_module(f"{__name__}.draft")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
