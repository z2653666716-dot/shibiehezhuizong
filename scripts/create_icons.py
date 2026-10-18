"""用简单几何形状生成192/512的PWA图标，不读取用户图片，输出到web/icons。"""
from pathlib import Path
from PIL import Image, ImageDraw


def main():
    """输入固定尺寸和配色，绘制取景框与V标记，供manifest引用。"""
    directory = Path(__file__).resolve().parents[1] / "web/icons"
    directory.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        image = Image.new("RGB", (size, size), "#101820")
        draw, unit = ImageDraw.Draw(image), size / 100
        draw.line([(round(x * unit), round(y * unit)) for x, y in [(30, 32), (50, 68), (70, 32)]],
                  fill="#41e18b", width=round(7 * unit))
        for x, y, dx, dy in [(20, 20, 1, 1), (80, 20, -1, 1), (20, 80, 1, -1), (80, 80, -1, -1)]:
            draw.line([(round((x + dx * 12) * unit), round(y * unit)), (round(x * unit), round(y * unit)),
                       (round(x * unit), round((y + dy * 12) * unit))], fill="white", width=round(3 * unit))
        image.save(directory / f"icon-{size}.png")


if __name__ == "__main__":
    main()
