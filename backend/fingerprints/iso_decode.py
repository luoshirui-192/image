"""ISO 19794-2 FMR feature decode (decodeISOV1.1 IsoFeatureToMinutiae)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Calibrated against Bidiso/neuiso batmatch_out samples (not C-file comment defaults).
DEFAULT_SETLEN = 0
DEFAULT_SETANG = 256
MAX_MINUTIA_COUNT = 200


@dataclass(frozen=True)
class Minutia:
    x: int
    y: int
    d: int
    t: int
    c: int = 0
    q: int = 0
    index: int = 0


@dataclass
class MinutiaeResult:
    count: int
    minutiae: list[Minutia]
    setlen: int
    setang: int

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "setlen": self.setlen,
            "setang": self.setang,
            "minutiae": [asdict(m) for m in self.minutiae],
        }


class IsoDecodeError(ValueError):
    """Raised when ISO feature bytes cannot be decoded."""


def iso_feature_to_minutiae(
    iso_data: bytes | bytearray,
    *,
    setlen: int = DEFAULT_SETLEN,
    setang: int = DEFAULT_SETANG,
) -> MinutiaeResult:
    """
    Parse ISO feature buffer into minutiae.

    Mirrors decodeISOV1.1 IsoFeatureToMinutiae:
      - minutia count at offset 27 + setlen
      - each minutia is 6 bytes starting at 28 + setlen
      - D = 360 - b4 * 360 / setang
    """
    if iso_data is None:
        raise IsoDecodeError("ISO data is required")
    if setlen < 0 or setang <= 0:
        raise IsoDecodeError("invalid setlen/setang")

    data = memoryview(iso_data)
    iso_len = len(data)
    base_offset = 27 + setlen
    if iso_len > 0 and base_offset >= iso_len:
        raise IsoDecodeError("ISO buffer too short for minutiae count")

    minucnt = int(data[base_offset])
    if minucnt > MAX_MINUTIA_COUNT:
        minucnt = MAX_MINUTIA_COUNT

    need_len = 28 + setlen + minucnt * 6
    if iso_len > 0 and need_len > iso_len:
        raise IsoDecodeError("ISO buffer too short for minutiae records")

    minutiae: list[Minutia] = []
    for i in range(minucnt):
        off = 28 + setlen + 6 * i
        b0 = int(data[off + 0])
        b1 = int(data[off + 1])
        b2 = int(data[off + 2])
        b3 = int(data[off + 3])
        b4 = int(data[off + 4])
        # off + 5 reserved / unused

        x = (b0 & 0x3F) * 256 + b1
        y = (b2 & 0x3F) * 256 + b3
        d = 360 - b4 * 360 // setang
        t = ((b0 & 0xC0) >> 6) - 1
        minutiae.append(Minutia(x=x, y=y, d=d, t=t, c=0, q=0, index=i + 1))

    return MinutiaeResult(count=minucnt, minutiae=minutiae, setlen=setlen, setang=setang)


def build_minimal_fmr(
    minutiae: list[tuple[int, int, int, int]],
    *,
    width: int = 400,
    height: int = 400,
    setlen: int = DEFAULT_SETLEN,
) -> bytes:
    """
    Build a tiny FMR buffer for tests.

    minutiae tuples: (x, y, angle_byte, type_bits) where type_bits is 0..3 in high bits of X word.
    """
    count = min(len(minutiae), MAX_MINUTIA_COUNT)
    body_len = 28 + setlen + count * 6
    total = body_len + 2  # trailing zeros like batmatch samples
    buf = bytearray(total)
    buf[0:4] = b"FMR\x00"
    buf[4:8] = b" 20\x00"
    buf[8:12] = total.to_bytes(4, "big")
    buf[14:16] = width.to_bytes(2, "big")
    buf[16:18] = height.to_bytes(2, "big")
    buf[18:20] = (197).to_bytes(2, "big")
    buf[20:22] = (197).to_bytes(2, "big")
    buf[22] = 1
    buf[27 + setlen] = count
    for i, (x, y, angle_byte, type_bits) in enumerate(minutiae[:count]):
        off = 28 + setlen + 6 * i
        high = (type_bits & 0x3) << 6
        buf[off] = high | ((x >> 8) & 0x3F)
        buf[off + 1] = x & 0xFF
        buf[off + 2] = (y >> 8) & 0x3F
        buf[off + 3] = y & 0xFF
        buf[off + 4] = angle_byte & 0xFF
        buf[off + 5] = 0
    return bytes(buf)
