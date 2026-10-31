"""Generate the tray icons (PNG) and the application icon (ICO) with Pillow.

Run ``python packaging/icons/make_icons.py`` from the repository root. It
writes ``tray-idle.png``, ``tray-working.png``, ``tray-warning.png`` and
``app.ico`` next to this script and copies the PNGs into
``src/word_session/assets/``.
"""

import shutil
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 64  # edge of the square tray images in pixels
VARIANTS = {  # state name -> bookmark colour
    "idle": (37, 99, 235),
    "working": (245, 158, 11),
    "warning": (220, 38, 38),
}


def draw_icon(bookmark: tuple[int, int, int], size: int = SIZE) -> Image.Image:
    """Draw a white page with a coloured bookmark on a transparent canvas."""
    scale = size / SIZE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(*coords: float) -> list[float]:
        return [c * scale for c in coords]

    # Page with a dark outline.
    draw.rounded_rectangle(
        box(10, 4, 54, 60),
        radius=6 * scale,
        fill=(255, 255, 255, 255),
        outline=(55, 65, 81, 255),
        width=max(1, round(3 * scale)),
    )

    # Text lines on the page.
    for y in (30, 38, 46):
        draw.rectangle(box(18, y, 40, y + 3), fill=(156, 163, 175, 255))

    # Bookmark ribbon hanging from the top edge.
    draw.polygon(box(36, 4, 50, 4, 50, 28, 43, 22, 36, 28), fill=(*bookmark, 255))
    return image


def main() -> None:
    """Write all icons and copy the tray PNGs into the package assets."""
    here = Path(__file__).resolve().parent
    assets = here.parents[1] / "src" / "word_session" / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    # One PNG per state, copied into the package.
    for name, colour in VARIANTS.items():
        target = here / f"tray-{name}.png"
        draw_icon(colour).save(target)
        shutil.copyfile(target, assets / target.name)

    # A multi-size ICO for the executable and shortcuts.
    draw_icon(VARIANTS["idle"], 256).save(
        here / "app.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
