import pytest
from construct import Container as C
from construct import ListContainer as L
from retro_data_structures.formats import effect_script as effects
from retro_data_structures.game_check import Game

from nullphaaze_crossgame.gc.corruption_particle_curves import lower_counter_curve


def evaluate(node, frame, counter):
    kind, body = node.type, node.body
    if kind == "CNST":
        if isinstance(body, dict):
            return [evaluate(v, frame, counter) for k, v in body.items() if k != "_io"]
        return body
    if kind == "GTCP":
        return counter
    if kind == "TSCL":
        return int(frame * evaluate(body, frame, counter))
    if kind in ("ADD_", "SUB_", "MODU"):
        a, b = evaluate(body.a, frame, counter), evaluate(body.b, frame, counter)
        return {"ADD_": lambda: a + b, "SUB_": lambda: a - b, "MODU": lambda: a % b}[kind]()
    if kind == "CHAN":
        switch = evaluate(body.c, frame, counter)
        return evaluate(body.a, frame, counter) if frame < switch else evaluate(body.b, frame - switch, counter)
    raise AssertionError(kind)


@pytest.mark.parametrize("width", [3, 4])
@pytest.mark.parametrize("loop", [False, True])
def test_counter_lookup_matches_source_integer_input_before_and_after_wrap(width, loop):
    keys = L([[float(i + channel / 10) for channel in range(width)] for i in range(8)])
    source = C(
        type="KEYF", body=C(a=2, b=0, c=loop, d=False, e=8, f=0, g=0.0, h=1.0, keys=keys, i=C(type="GTCP", body=None))
    )
    converted = lower_counter_curve(source)
    codec = effects.GetVectorElement if width == 3 else effects.GetColorElement
    # Check the destination grammar as well as numeric branch behavior.
    converted = codec.parse(codec.build(converted, target_game=Game.PRIME), target_game=Game.PRIME)
    for count in range(100):
        index = count % 8 if loop else min(count, 7)
        if loop and count >= 8 and 0 < index < 7:
            index += 1
        for frame in (0, 1, 17, 500):
            assert evaluate(converted, frame, count) == pytest.approx(keys[index])
