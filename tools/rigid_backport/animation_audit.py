"""Original compression oracle isolated from host/cache inspection code."""
import math
from collections import Counter
from retro_data_structures.formats.anim import Anim
from retro_data_structures.game_check import Game
from nullphaaze_crossgame.gc.corruption_animation import decode, encode, encode_compressed
from native_animation import retail_key_deltas

def audit_compression(clip, game, payload=None):
    source_norm_error = max(
        (
            abs(sum(component * component for component in key) - 1)
            for track in clip.tracks.values()
            if track.rotation is not None
            for key in track.rotation
        ),
        default=0.0,
    )
    # Check source validity before both encoders share the same decoded input.
    # Otherwise a source accumulator overflow can pass a round-trip comparison.
    assert source_norm_error < 0.001, ("non-unit source quaternion", source_norm_error)
    reference = Anim.parse(encode(clip, game), game).raw.anim
    if payload is None:
        payload = encode_compressed(clip, game)
    native = Anim.parse(payload, game).raw.anim
    native_frames = retail_key_deltas(payload, game)
    maxima = Counter()
    count = reference.key_count
    for channel_index, descriptor in enumerate(native.bone_channel_descriptors):
        source_channel = reference.bone_channel_index_array[descriptor.bone_id]
        for kind in ("rotation", "translation", "scale"):
            initial = descriptor[kind + "_keys"]
            if initial is None:
                continue
            mapping = reference[kind + "_channel_index_array"]
            source_index = source_channel if mapping is None else mapping[source_channel]
            values = reference[kind + "_key_array"][source_index * count : (source_index + 1) * count]
            state = [initial["initial_" + a] for a in ("x", "y", "z")]
            state = [value if value < 32768 else value - 65536 for value in state]
            sign = 0
            for frame_index in range(count):
                if frame_index:
                    frame_sign, delta = native_frames[frame_index - 1][channel_index][kind]
                    if frame_sign is not None:
                        sign = frame_sign
                    for i, axis in enumerate(("x", "y", "z")):
                        state[i] += delta[i]
                signed = state
                if kind == "rotation":
                    xyz = [math.sin(v * math.pi / (2 * native.rotation_divisor)) for v in signed]
                    actual = [math.sqrt(max(0, 1 - sum(v * v for v in xyz))) * (-1 if sign else 1), *xyz]
                    expected = values[frame_index]
                    dot = abs(sum(a * b for a, b in zip(actual, expected)))
                    error = 2 * math.acos(min(1, dot))
                    assert error < math.radians(1), (
                        kind,
                        descriptor.bone_id,
                        frame_index,
                        error,
                        actual,
                        expected,
                        state,
                    )
                else:
                    multiplier = native[kind + "_multiplier"]
                    error = max(abs(v * multiplier - e) for v, e in zip(signed, values[frame_index]))
                    assert error <= multiplier * 0.501 + 0.000001, (kind, error, multiplier)
                maxima[kind] = max(maxima[kind], error)
    return {**dict(maxima), "source_quaternion_norm_error": source_norm_error}
