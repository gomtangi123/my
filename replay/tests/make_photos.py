"""E2E 테스트용 사진 묶음을 만든다.

    python replay/tests/make_photos.py <출력 폴더>

만드는 것 (파일 이름 앞글자가 기대 결과):
  keep_*      남아야 하는 사진
  burst_*     연속 촬영 3장 → 가장 선명한 burst_b만 남는다
  blurry_*    흔들린 사진
  shot_*      스크린샷 (PNG, EXIF 없음)
  dark_*      너무 어두운 사진
  broken_*    깨진 파일
  KakaoTalk_* EXIF 없이 이름에만 날짜 → 남는다
  music.wav   6초짜리 배경음
"""

from __future__ import annotations

import math
import random
import struct
import sys
import wave
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def scene(seed: int, size: tuple[int, int]) -> Image.Image:
    rnd = random.Random(seed)
    w, h = size
    top = tuple(rnd.randrange(40, 220) for _ in range(3))
    bottom = tuple(rnd.randrange(40, 220) for _ in range(3))
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    for _ in range(40):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.randrange(20, w // 4)
        color = tuple(rnd.randrange(256) for _ in range(3))
        if rnd.random() < 0.5:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        else:
            draw.rectangle([x - r, y - r // 2, x + r, y + r // 2], fill=color, outline=(255, 255, 255), width=4)
    # 잔결(텍스처)이 있어야 선명도가 실제 사진처럼 나온다
    noise = Image.effect_noise(size, 40).convert("RGB")
    return Image.blend(img, noise, 0.12)


def exif_bytes(when: datetime, lat: float | None = None, lon: float | None = None) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "TestPhone"
    exif[0x0110] = "Camera 1"
    exif.get_ifd(0x8769)[0x9003] = when.strftime("%Y:%m:%d %H:%M:%S")
    if lat is not None and lon is not None:
        gps = exif.get_ifd(0x8825)

        def dms(value: float) -> tuple[float, float, float]:
            value = abs(value)
            d = int(value)
            m = int((value - d) * 60)
            return (float(d), float(m), round(((value - d) * 60 - m) * 60, 2))

        gps[1] = "N" if lat >= 0 else "S"
        gps[2] = dms(lat)
        gps[3] = "E" if lon >= 0 else "W"
        gps[4] = dms(lon)
    return exif.tobytes()


def save(img: Image.Image, path: Path, when: datetime | None, **gps) -> None:
    if when is None:
        img.save(path, "JPEG", quality=88)
    else:
        img.save(path, "JPEG", quality=88, exif=exif_bytes(when, **gps))


def music(path: Path, seconds: float = 6.0, rate: int = 44100) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            t = i / rate
            value = 0.3 * math.sin(2 * math.pi * 440 * t) * (0.6 + 0.4 * math.sin(2 * math.pi * 2 * t))
            frames += struct.pack("<h", int(value * 32767))
        out.writeframes(bytes(frames))


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    portrait = (900, 1200)
    landscape = (1200, 900)
    day1 = datetime(2026, 9, 5, 10, 0, 0)
    day2 = datetime(2026, 9, 12, 14, 0, 0)

    seoul = dict(lat=37.5665, lon=126.9780)
    for i in range(4):
        save(scene(100 + i, portrait), out / f"keep_day1_{i}.jpg", day1 + timedelta(hours=i), **seoul)

    # 연속 촬영: 같은 장면에 흔들림 정도만 다르게, 2초 간격
    base = scene(200, portrait)
    for name, radius, sec in (("a", 2.5, 0), ("b", 0, 2), ("c", 1.5, 4)):
        img = base.filter(ImageFilter.GaussianBlur(radius)) if radius else base
        save(img, out / f"burst_{name}.jpg", day1 + timedelta(hours=5, seconds=sec), **seoul)

    busan = dict(lat=35.1796, lon=129.0756)
    save(scene(300, landscape), out / "keep_day2_landscape.jpg", day2, **busan)
    save(scene(301, portrait), out / "keep_day2_1.jpg", day2 + timedelta(hours=1), **busan)
    save(scene(302, portrait), out / "keep_day2_2.jpg", day2 + timedelta(hours=2), **busan)
    save(
        scene(303, portrait).filter(ImageFilter.GaussianBlur(9)),
        out / "blurry_day2.jpg",
        day2 + timedelta(hours=3),
        **busan,
    )
    save(Image.new("RGB", portrait, (6, 6, 8)), out / "dark_day2.jpg", day2 + timedelta(hours=4))

    shot = scene(400, (1080, 2340))
    ImageDraw.Draw(shot).rectangle([0, 0, 1080, 120], fill=(250, 250, 250))
    shot.save(out / "shot_Screenshot_20260913-101010.png")

    save(scene(500, portrait), out / "KakaoTalk_20260920_101500123.jpg", None)
    (out / "broken_file.jpg").write_bytes(b"\xff\xd8\xff\xe0 this is not really a jpeg" * 20)

    music(out / "music.wav")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "replay-test-photos"))
