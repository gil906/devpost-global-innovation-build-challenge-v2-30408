"""Check actual PNG dimensions and WebM metadata, including the 2-5 minute limit."""

import struct
from pathlib import Path


def elements(data, start=0, end=None):
    end = len(data) if end is None else end
    cursor = start
    while cursor < end:
        if not data[cursor]:
            raise ValueError("Invalid EBML element ID")
        id_width = 9 - data[cursor].bit_length()
        identifier = int.from_bytes(data[cursor:cursor + id_width], "big")
        cursor += id_width
        size_width = 9 - data[cursor].bit_length()
        size = int.from_bytes(data[cursor:cursor + size_width], "big") & ((1 << (7 * size_width)) - 1)
        cursor += size_width
        if size == (1 << (7 * size_width)) - 1:
            size = end - cursor
        if cursor + size > end:
            raise ValueError("Truncated EBML element")
        yield identifier, cursor, cursor + size
        cursor += size


def video_metadata(path):
    data = path.read_bytes()
    segment = next((start, end) for tag, start, end in elements(data) if tag == 0x18538067)
    info = next((start, end) for tag, start, end in elements(data, *segment) if tag == 0x1549A966)
    scale, duration = 1000000, None
    for tag, start, end in elements(data, *info):
        if tag == 0x2AD7B1:
            scale = int.from_bytes(data[start:end], "big")
        elif tag == 0x4489:
            duration = struct.unpack(">d" if end - start == 8 else ">f", data[start:end])[0]
    if duration is None:
        raise ValueError("Video has no recorded duration.")
    tracks = next((start, end) for tag, start, end in elements(data, *segment) if tag == 0x1654AE6B)
    width = height = 0
    for tag, start, end in elements(data, *tracks):
        if tag != 0xAE:
            continue
        for child, first, last in elements(data, start, end):
            if child == 0xE0:
                for field, begin, finish in elements(data, first, last):
                    if field == 0xB0:
                        width = int.from_bytes(data[begin:finish], "big")
                    elif field == 0xBA:
                        height = int.from_bytes(data[begin:finish], "big")
    return duration * scale / 1e9, width, height


def main():
    directory = Path("docs/media")
    screenshots = [
        "01-plan-overview.png", "02-supply-and-hubs.png",
        "03-method-and-evidence.png", "04-mobile-plan.png",
    ]
    for index, filename in enumerate(screenshots):
        data = (directory / filename).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise SystemExit(f"Not a PNG: {filename}")
        width, height = struct.unpack(">II", data[16:24])
        if width < (1280 if index < 3 else 390) or height < 720:
            raise SystemExit(f"Screenshot is too small: {filename}")
        print(f"PASS: {filename}: {width} x {height}")
    duration, width, height = video_metadata(directory / "commontable-demo.webm")
    if not 120 <= duration <= 300 or width < 1280 or height < 720:
        raise SystemExit(f"Demo does not meet duration/resolution bounds: {duration}s, {width}x{height}")
    print(f"PASS: demo video: {duration:.2f} seconds, {width} x {height}; within the 2-5 minute requirement.")


if __name__ == "__main__":
    main()
