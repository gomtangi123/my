"""사진을 카드에 까는 일.

글씨만 있는 카드는 심심하지만, 사진을 깔면 **글씨가 안 읽히는** 문제가 바로
생긴다. 밝은 하늘 위에 흰 글씨를 얹으면 그냥 사라진다.

그래서 장막(scrim)의 진하기를 눈대중으로 정하지 않는다. 글씨가 놓일 자리의
픽셀 휘도를 실제로 재서, 목표 대비가 나올 때까지 장막을 진하게 한다.
평균이 아니라 **최악의 픽셀**(밝은 글씨면 가장 밝은 쪽)을 기준으로 잡는다 —
평균으로 재면 사진 한구석의 밝은 부분에서 글씨가 묻힌다.
"""

from __future__ import annotations

from . import colors

# 휘도를 잴 때 줄이는 크기. 이 정도면 밝은 얼룩을 놓치지 않으면서 충분히 빠르다.
SAMPLE = 48
# 장막 진하기 후보. 옅은 것부터 시도해서 조건을 만족하는 첫 값을 쓴다.
ALPHAS = (0.25, 0.35, 0.45, 0.55, 0.65, 0.72, 0.80, 0.88)


def cover_crop(image, width: int, height: int):
    """비율을 지키며 꽉 채우고, 넘치는 부분은 가운데를 기준으로 자른다."""
    from PIL import Image  # type: ignore

    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("빈 이미지입니다.")
    scale = max(width / src_w, height / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    resized = image.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
    left, top = (new_w - width) // 2, (new_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


def extreme_luminance(image, box: tuple[int, int, int, int], bright: bool) -> float:
    """상자 안에서 글씨에 가장 불리한 휘도.

    `bright=True`(밝은 글씨)면 가장 밝은 쪽을, 아니면 가장 어두운 쪽을 본다.
    한 점짜리 튀는 픽셀에 휘둘리지 않도록 5% 지점을 쓴다.
    """
    from PIL import Image  # type: ignore

    left, top, right, bottom = box
    left, top = max(0, left), max(0, top)
    right, bottom = min(image.width, right), min(image.height, bottom)
    if right <= left or bottom <= top:
        return 0.5

    patch = image.crop((left, top, right, bottom)).convert("RGB")
    patch = patch.resize((SAMPLE, SAMPLE), Image.BILINEAR)
    # tobytes()는 Pillow 판올림을 타지 않는다 (getdata()는 14에서 없어진다).
    raw = patch.tobytes()
    lums = sorted(
        colors.luminance_rgb((raw[i], raw[i + 1], raw[i + 2]))
        for i in range(0, len(raw) - 2, 3)
    )
    index = int(len(lums) * (0.95 if bright else 0.05))
    return lums[min(index, len(lums) - 1)]


def scrim_alpha(
    image,
    box: tuple[int, int, int, int],
    text: str,
    veil: str,
    minimum: float = 4.5,
) -> float:
    """목표 대비가 나오는 가장 옅은 장막 진하기.

    어떤 진하기로도 모자라면 가장 진한 값을 돌려준다 — 여기서 포기하면
    사진 한 장 때문에 카드가 아예 안 나온다.
    """
    text_lum = colors.luminance(text)
    veil_rgb = colors.parse(veil)

    # 밝은 글씨는 배경이 밝을수록 불리하고, 어두운 글씨는 그 반대다.
    # 그래서 글씨가 밝으면 가장 밝은 쪽을, 어두우면 가장 어두운 쪽을 본다.
    worst = extreme_luminance(image, box, bright=text_lum > 0.5)

    for alpha in ALPHAS:
        # 장막을 씌운 뒤의 휘도는 원래 픽셀과 장막색을 alpha로 섞은 것.
        mixed = _blend_luminance(worst, veil_rgb, alpha)
        if colors.contrast_lum(text_lum, mixed) >= minimum:
            return alpha
    return ALPHAS[-1]


def _blend_luminance(source_lum: float, veil_rgb, alpha: float) -> float:
    """휘도 값 하나를 장막색과 섞었을 때의 휘도.

    정확히는 채널별로 섞어야 하지만, 장막은 단색이고 우리가 쓰는 건
    '얼마나 가려지는가'뿐이라 휘도 선형 보간으로 충분하다.
    """
    veil_lum = colors.luminance_rgb(veil_rgb)
    return source_lum * (1 - alpha) + veil_lum * alpha


def apply_scrim(image, veil: str, alpha: float):
    """카드 전체에 단색 장막을 씌운다."""
    from PIL import Image  # type: ignore

    veil_layer = Image.new("RGB", image.size, veil)
    return Image.blend(image.convert("RGB"), veil_layer, max(0.0, min(1.0, alpha)))


def gradient_scrim(
    image, veil: str, peak: float, start: float = 0.22, hold: float = 0.50
):
    """위는 그대로 두고 아래로 갈수록 진해지다, `hold` 부터는 `peak` 를 유지한다.

    카드 전체를 고르게 덮으면 사진이 통째로 탁해진다. 글은 아래쪽에만 있으니
    거기만 가리면 위쪽 사진은 살아 있고 글도 읽힌다.

    `hold` 가 핵심이다. 맨 밑에서만 `peak` 에 닿게 만들면 정작 제목이 있는
    중간 높이는 거의 안 덮여서 글씨가 사진에 묻힌다. 글이 시작하는 높이에서
    이미 `peak` 에 도달해 있어야 한다.
    """
    from PIL import Image  # type: ignore

    width, height = image.size
    peak = max(0.0, min(1.0, peak))
    begin = max(0, min(height - 1, int(height * start)))
    full = max(begin + 1, min(height, int(height * hold)))
    span = full - begin

    mask = Image.new("L", (1, height))
    pixels = mask.load()
    for y in range(height):
        if y <= begin:
            value = 0.0
        elif y >= full:
            value = peak
        else:
            # 직선으로 올리면 경계가 띠처럼 보여서 살짝 휘어 올린다.
            value = peak * (((y - begin) / span) ** 1.5)
        pixels[0, y] = int(round(255 * value))

    veil_layer = Image.new("RGB", (width, height), veil)
    return Image.composite(
        veil_layer, image.convert("RGB"), mask.resize((width, height))
    )


# 사진을 그라데이션으로 펼 때 남길 격자. 이보다 잘게 나누면 사진의 형태가
# 남아서 글씨를 방해하고, 더 성기면 그냥 단색 두어 개가 된다.
WASH_GRID = (3, 4)


def gradient_from(image, width: int, height: int, softness: float = 0.06):
    """사진을 색만 남긴 그라데이션으로 편다.

    표나 그래프 뒤에 사진을 그대로 깔면 가는 선과 작은 글씨가 묻힌다.
    그렇다고 사진을 빼면 앞뒤 카드와 따로 논다. 사진을 아주 잘게 줄였다가
    다시 키우면 형태는 사라지고 색과 밝기 배치만 남는다 — 같은 사진에서
    나온 배경이라 덱의 흐름은 이어지고, 글씨는 읽힌다.
    """
    from PIL import Image, ImageFilter  # type: ignore

    source = cover_crop(image, width, height)
    tiny = source.resize(WASH_GRID, Image.BOX)  # 칸마다 평균색
    spread = tiny.resize((width, height), Image.BICUBIC)
    return spread.filter(ImageFilter.GaussianBlur(max(1.0, width * softness)))


__all__ = [
    "cover_crop",
    "extreme_luminance",
    "scrim_alpha",
    "apply_scrim",
    "gradient_scrim",
    "gradient_from",
    "WASH_GRID",
    "ALPHAS",
]
