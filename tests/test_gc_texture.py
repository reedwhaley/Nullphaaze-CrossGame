import struct

import pytest

from nullphaaze_crossgame.gc.corruption_texture import atlas_frame


@pytest.mark.parametrize(("phase", "pixel"), [(-1.0, 3), (0.0, 3), (0.25, 4), (0.5, 1), (1.0, 2), (2.0, 2)])
def test_constant_phase_selects_source_frame_and_its_small_mip_texels(phase, pixel):
    # Native 4x4 GX blocks, with a distinguishable value in each atlas cell.
    level_zero = b"".join(struct.pack(">H", n) * 16 for n in (1, 2, 3, 4))
    level_one = b"".join(struct.pack(">H", n) for n in (1, 1, 2, 2) * 2 + (3, 3, 4, 4) * 2)
    original = struct.pack(">IHHI", 8, 8, 8, 2) + level_zero + level_one
    result, index = atlas_frame(original, 4, 4, phase)
    assert struct.unpack_from(">IHHI", result) == (8, 4, 4, 2)
    assert result[12:] == struct.pack(">H", pixel) * 32
    assert index == max(0, min(3, int(phase * 4)))


def test_truncated_phase_texture_is_rejected():
    with pytest.raises(ValueError, match="Truncated"):
        atlas_frame(struct.pack(">IHHI", 8, 8, 8, 1), 4, 4, 0.0)


@pytest.mark.parametrize(("phase", "cell"), [(0.0, 0), (0.25, 1), (0.5, 2), (1.0, 3)])
def test_compressed_atlas_preserves_source_endpoints_and_small_mip_indices(phase, cell):
    blocks = [struct.pack(">HH", i + 1, i + 10) + bytes(4) for i in range(4)]
    # At mip one all four atlas cells occupy one 4x4 DXT block.
    mip = struct.pack(">HH", 0xF800, 0x07E0) + bytes([0x05, 0x05, 0xAF, 0xAF])
    payload = struct.pack(">IHHI", 10, 8, 8, 2) + b"".join(blocks) + mip * 4
    result, _ = atlas_frame(payload, 4, 4, phase)
    # TEXP enumeration runs bottom-to-top.
    selected = [2, 3, 0, 1][cell]
    assert result[12:44] == blocks[selected] * 4
    expected = struct.pack(">HH", 0xF800, 0x07E0) + bytes([selected * 0x55]) * 4
    assert result[44:] == expected * 4
