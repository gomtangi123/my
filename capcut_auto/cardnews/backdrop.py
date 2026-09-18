"""사진 없이 만드는 배경.

남의 사진은 변형해도 저작권이 따라온다. 스톡 사이트를 쓰든 직접 찍든
출처가 깨끗해야 하는데, 경제 카드뉴스에서는 애초에 사진이 꼭 필요하지도
않다 — 흔한 스톡 사진은 오히려 "어디서 본 계정" 이 되게 만든다.

그래서 테마 색으로 배경을 **만들어** 쓴다. 코드가 그린 것이므로 출처
문제가 없고, 덱 전체가 같은 색을 쓰니 한 벌로 보인다.

같은 카드는 늘 같은 배경이 나와야 한다. 다시 돌릴 때마다 배경이 바뀌면
올려 둔 것과 달라지기 때문에, 난수는 카드 글에서 뽑은 씨앗으로 고정한다.
"""

from __future__ import annotations

import hashlib
import math
import random

from . import colors

STYLES = ("mesh", "grid", "rays", "dots")
DEFAULT_STYLE = "mesh"

# 메시는 작게 그려서 키운다 — 어차피 흐린 그림이라 원본 해상도가 필요 없다.
MESH_GRID = 72


def seed_of(text: str) -> int:
    """카드 글에서 고정 씨앗. 같은 글이면 늘 같은 배경."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def palette(bg: str, fg: str, accent: str) -> list[str]:
    """배경에 쓸 색. 테마 색에서만 뽑아 쓴다 — 덱이 한 벌로 보여야 한다."""
    return [
        bg,
        colors.mix(bg, accent, 0.30),
        colors.mix(bg, accent, 0.58),
        accent,
        colors.mix(bg, fg, 0.14),
    ]


def make(
    style: str,
    width: int,
    height: int,
    bg: str,
    fg: str,
    accent: str,
    seed: int = 0,
):
    """배경 이미지 하나. 모르는 이름이면 ValueError."""
    if style not in STYLES:
        raise ValueError(f"모르는 배경입니다: {style} (가능: {', '.join(STYLES)})")
    rng = random.Random(seed)
    tones = palette(bg, fg, accent)
    if style == "mesh":
        return _mesh(width, height, tones, rng)
    if style == "grid":
        return _grid(width, height, bg, fg, accent, rng)
    if style == "rays":
        return _rays(width, height, bg, accent, rng)
    return _dots(width, height, bg, fg, accent, rng)


def _mesh(width: int, height: int, tones: list[str], rng: random.Random):
    """색 덩어리 몇 개를 흐리게 섞은 그라데이션. 요즘 흔한 그 배경이다."""
    from PIL import Image, ImageFilter  # type: ignore

    small_w = MESH_GRID
    small_h = max(1, int(MESH_GRID * height / width))
    canvas = Image.new("RGB", (small_w, small_h), tones[0])
    pixels = canvas.load()

    # 색 덩어리의 중심점들. 각 픽셀은 가까운 중심의 색을 거리로 가중해 받는다.
    points = [
        (
            rng.uniform(-0.15, 1.15) * small_w,
            rng.uniform(-0.15, 1.15) * small_h,
            colors.parse(rng.choice(tones[1:])),
            rng.uniform(0.35, 0.85) * small_w,
        )
        for _ in range(rng.randint(4, 6))
    ]
    base = colors.parse(tones[0])
    for y in range(small_h):
        for x in range(small_w):
            r = g = b = 0.0
            total = 0.0
            for px, py, colour, reach in points:
                d = math.hypot(x - px, y - py)
                weight = max(0.0, 1.0 - d / reach) ** 2
                r += colour[0] * weight
                g += colour[1] * weight
                b += colour[2] * weight
                total += weight
            if total <= 0:
                pixels[x, y] = base
            else:
                # 바탕색을 조금 남겨야 너무 알록달록해지지 않는다.
                k = min(1.0, total)
                pixels[x, y] = (
                    int(base[0] * (1 - k) + r / total * k),
                    int(base[1] * (1 - k) + g / total * k),
                    int(base[2] * (1 - k) + b / total * k),
                )

    from PIL import Image as _Image

    out = canvas.resize((width, height), _Image.BICUBIC)
    return out.filter(ImageFilter.GaussianBlur(width * 0.02))


def _grid(width: int, height: int, bg: str, fg: str, accent: str, rng: random.Random):
    """가는 격자 + 가장자리 어둡게. 표·숫자 카드와 잘 어울린다."""
    from PIL import Image, ImageDraw, ImageFilter  # type: ignore

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    line = colors.mix(bg, fg, 0.10)
    step = max(24, width // 14)
    offset = rng.randrange(step)
    for x in range(-offset, width + step, step):
        draw.line([(x, 0), (x, height)], fill=line, width=max(1, width // 900))
    for y in range(-offset, height + step, step):
        draw.line([(0, y), (width, y)], fill=line, width=max(1, width // 900))

    # 강조색 사선 하나. 격자만 있으면 심심하다.
    glow = Image.new("RGB", (width, height), bg)
    ImageDraw.Draw(glow).polygon(
        [(0, height * 0.62), (width, height * 0.18), (width, height), (0, height)],
        fill=colors.mix(bg, accent, 0.22),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(width * 0.06))
    return Image.blend(image, glow, 0.55)


def _rays(width: int, height: int, bg: str, accent: str, rng: random.Random):
    """비스듬한 넓은 띠. 흐려 놓으면 빛이 비치는 것처럼 보인다."""
    from PIL import Image, ImageDraw, ImageFilter  # type: ignore

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    band = colors.mix(bg, accent, 0.26)
    span = max(40, width // 6)
    slant = rng.uniform(0.4, 0.9) * height
    x = -height
    while x < width + height:
        draw.polygon(
            [(x, height), (x + span, height), (x + span + slant, 0), (x + slant, 0)],
            fill=band,
        )
        x += span * 2
    return image.filter(ImageFilter.GaussianBlur(width * 0.035))


def _dots(width: int, height: int, bg: str, fg: str, accent: str, rng: random.Random):
    """점이 아래로 갈수록 커지는 망점 배경."""
    from PIL import Image, ImageDraw, ImageFilter  # type: ignore

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    tone = colors.mix(bg, accent, 0.34)
    step = max(18, width // 26)
    jitter = rng.uniform(0.0, step)
    for row, y in enumerate(range(0, height + step, step)):
        t = y / height
        radius = step * (0.08 + 0.30 * t)
        shift = (step / 2) if row % 2 else 0
        for x in range(0, width + step, step):
            cx = x + shift + jitter
            draw.ellipse([cx - radius, y - radius, cx + radius, y + radius], fill=tone)
    return image.filter(ImageFilter.GaussianBlur(width * 0.004))


__all__ = ["STYLES", "DEFAULT_STYLE", "make", "palette", "seed_of"]
