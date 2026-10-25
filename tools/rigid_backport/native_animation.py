"""Read emitted GC animation deltas with the retail least-significant-bit order.

RDS supplies only the byte-aligned descriptors. Its bit-field parser is not used
to interpret the animation stream, avoiding a matching encoder/decoder error.
"""

import struct

from retro_data_structures.formats.anim import Anim
from retro_data_structures.game_check import Game


def retail_key_deltas(payload, game):
    animation = Anim.parse(payload, game).raw.anim
    kinds = ("rotation", "translation") if game == Game.PRIME else ("rotation", "translation", "scale")
    bits_per_frame = sum(
        (kind == "rotation") + sum(descriptor[kind + "_keys"]["delta_" + axis] for axis in "xyz")
        for descriptor in animation.bone_channel_descriptors
        for kind in kinds
        if descriptor[kind + "_keys"] is not None
    )
    count = len(animation.animation_keys)
    word_count = (bits_per_frame * count + 31) // 32
    words = struct.unpack(f">{word_count}I", payload[-word_count * 4 :])
    position = 0

    def read(width, signed=True):
        nonlocal position
        value = 0
        for bit in range(width):
            value |= ((words[position // 32] >> (position % 32)) & 1) << bit
            position += 1
        return value - (1 << width) if signed and value & (1 << (width - 1)) else value

    frames = []
    for _ in range(count):
        channels = []
        for descriptor in animation.bone_channel_descriptors:
            channel = {}
            for kind in kinds:
                initial = descriptor[kind + "_keys"]
                if initial is None:
                    channel[kind] = None
                    continue
                sign = read(1, False) if kind == "rotation" else None
                channel[kind] = (sign, [read(initial["delta_" + axis]) for axis in "xyz"])
            channels.append(channel)
        frames.append(channels)
    return frames
