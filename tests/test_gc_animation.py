import math
import struct

import pytest
from retro_data_structures.formats.anim import Anim
from retro_data_structures.game_check import Game

from nullphaaze_crossgame.gc.corruption_animation import Bits, decode, encode, encode_compressed, interpolate
from native_animation import retail_key_deltas


def fixture_clip(initial_z=0, delta_z=16384):
    times = struct.pack(">2f", 0, 1)
    flags = bytes([1, 3])
    initial = struct.pack(">7h", 0, 0, 0, initial_z, 0, 0, 0)
    widths = bytes([0, 0, 0, 16, 5, 0, 0])
    words = struct.pack(">I", ((delta_z & 65535) << 1) | (10 << 17))
    stream = struct.pack(">3I", 7, 1, 7) + widths + words
    footer = struct.pack(">I", 1) + bytes([0])
    blob = times + flags + initial + stream + footer
    header = bytearray(65)
    struct.pack_into(">f", header, 10, 0.25)
    struct.pack_into(">fH", header, 30, 1, 2)
    for offset, value in zip(
        (36, 41, 45, 49, 53, 57, 61), (len(blob), len(times), len(flags), len(initial), len(stream), 0, 1)
    ):
        struct.pack_into(">I", header, offset, value)
    return struct.pack(">I", 1) + header + blob


def test_decode_known_rotation_translation():
    clip = decode(fixture_clip())
    assert clip.times == (0, 1)
    track = clip.tracks[0]
    assert track.translation == [(0, 0, 0), (2.5, 0, 0)]
    assert track.rotation[0] == (1, 0, 0, 0)
    assert track.rotation[1][3] == pytest.approx(16384 / 32767)
    assert sum(v * v for v in track.rotation[1]) == pytest.approx(1)


@pytest.mark.parametrize(("initial", "delta", "expected"), [(30000, 16384, -19152), (-30000, -16384, 19152)])
def test_source_rotation_accumulator_wraps_signed_sixteen_bits(initial, delta, expected):
    clip = decode(fixture_clip(initial, delta))
    rotation = clip.tracks[0].rotation[-1]
    assert rotation[3] == pytest.approx(expected / 32767)
    assert sum(v * v for v in rotation) == pytest.approx(1)


def test_every_truncated_prefix_rejected():
    clip = fixture_clip()
    for size in range(len(clip)):
        with pytest.raises((ValueError, struct.error)):
            decode(clip[:size])


@pytest.mark.parametrize(("game", "bone"), [(Game.PRIME, 3), (Game.ECHOES, 0)])
def test_native_array_encodes_source_endpoints_and_interpolation(game, bone):
    clip = decode(fixture_clip())
    result = Anim.parse(encode(clip, game), game).raw.anim
    assert result.key_count == 61
    assert result.bone_channel_index_array[bone] == 0
    assert result.translation_key_array[-1] == pytest.approx([2.5, 0, 0])
    assert result.translation_key_array[30] == pytest.approx([1.25, 0, 0])
    assert result.rotation_key_array[-1] == pytest.approx(clip.tracks[0].rotation[-1])
    assert result.rotation_key_array[30] == pytest.approx(
        interpolate(clip.tracks[0].rotation, clip.times, 0.5, quaternion=True)
    )


def test_signed_bits_cross_word_boundary():
    bits = Bits(struct.pack(">2I", 0x80000000, 3))
    for _ in range(31):
        assert bits.read(1) == 0
    assert bits.read(3, signed=True) == -1


def test_slerp_treats_quaternion_signs_as_same_rotation():
    assert interpolate([(1, 0, 0, 0), (-1, 0, 0, 0)], (0, 1), 0.5, True) == (1, 0, 0, 0)
    end = (math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4))
    assert interpolate([(1, 0, 0, 0), end], (0, 1), 0.5, True) == pytest.approx(
        (math.cos(math.pi / 8), 0, 0, math.sin(math.pi / 8))
    )


@pytest.mark.parametrize("game", [Game.PRIME, Game.ECHOES])
@pytest.mark.parametrize("direction", [-1, 1])
def test_retail_compression_reconstructs_every_frame_with_native_bit_order(game, direction):
    clip = decode(fixture_clip(delta_z=direction * 16384))
    encoded = encode_compressed(clip, game, event_id=1234)
    result = Anim.parse(encoded, game).raw
    assert result.anim_version == 2
    assert len(result.anim.animation_keys) == 60
    if game == Game.PRIME:
        assert result.anim.event_id == 1234
    descriptor = result.anim.bone_channel_descriptors[0]

    def initial(field):
        return [v if v < 32768 else v - 65536 for v in (field["initial_" + axis] for axis in "xyz")]

    xyz, translation = initial(descriptor.rotation_keys), initial(descriptor.translation_keys)
    for index, frame in enumerate(retail_key_deltas(encoded, game), 1):
        sign, rotation_delta = frame[0]["rotation"]
        _, translation_delta = frame[0]["translation"]
        xyz = [a + b for a, b in zip(xyz, rotation_delta)]
        translation = [a + b for a, b in zip(translation, translation_delta)]
        imaginary = [math.sin(v * math.pi / (2 * 32767)) for v in xyz]
        w = math.sqrt(max(0, 1 - sum(v * v for v in imaginary))) * (-1 if sign else 1)
        timestamp = index * result.anim.interval
        expected = interpolate(clip.tracks[0].rotation, clip.times, timestamp, True)
        assert [w, *imaginary] == pytest.approx(expected, abs=0.00005)
        expected_translation = interpolate(clip.tracks[0].translation, clip.times, timestamp)
        assert [v * result.anim.translation_multiplier for v in translation] == pytest.approx(
            expected_translation, abs=0.0001
        )
