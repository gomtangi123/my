"""CapCut 관련 예외.

`draft` 모듈에서 떼어 놓은 이유는 그쪽이 `pycapcut` 을 불러오기 때문이다.
카드뉴스처럼 CapCut 과 아무 상관 없는 기능도 이 예외를 잡아야 하는데,
그것 때문에 영상 라이브러리까지 깔게 할 수는 없다.
"""

from __future__ import annotations


class TemplateError(RuntimeError):
    """템플릿 드래프트를 읽거나 복제하지 못했을 때."""


__all__ = ["TemplateError"]
