import math

import pytest
from construct import Container as C
from construct import ListContainer as L
from retro_data_structures.formats.cskr import Cskr
from retro_data_structures.game_check import Game

from nullphaaze_crossgame.gc.corruption_animation import Animation, Track
from nullphaaze_crossgame.gc.corruption_character import (
    BOOST_BALL_CHARACTER,
    BOOST_TRAIL_BONE,
    BOOST_TRAIL_EFFECTS,
    BOOST_TRAIL_NAME,
    CHARGE_BEAM_CHARACTER,
    HAZARD_SHIELD_CHARACTER,
    HYPER_BARE_CHARACTERS,
    HYPERMODE_CHARACTER,
    align_pickup_internals,
    attached_particle_event,
    fit_hyper_presentation,
    fit_pickup_internals,
    prepare_pickup_skeleton,
    reindex_mesh,
    rotate,
)
from animation_audit import audit_compression


def fixture_rig():
    vertices = L([C(position=0, normal=0, matrix=C(position=m)) for m in (0, 3, 0)])
    mesh = C(
        surfaces=L([C(header=C(unk_1=0), primitives=L([C(vertices=vertices)]))]),
        attrib_arrays=C(positions=L([[2, 0, 0]]), normals=L([[1, 0, 0]])),
    )
    skin = C(
        footer=C(pool_to_skin_idx=L([0, 1])),
        vertex_groups=L([C(vertex_count=99, weights_array=L([C(bone_id=i, weight=1.0)])) for i in (0, 1)]),
    )
    angle = math.sqrt(0.5)
    skeleton = C(
        bones=L(
            [
                C(id=0, position=[1, 0, 0], rotation=[angle, 0, 0, angle]),
                C(id=1, position=[0, 0, 0], rotation=[1, 0, 0, 0]),
            ]
        )
    )
    return mesh, skin, skeleton


@pytest.mark.parametrize("game", [Game.PRIME, Game.ECHOES])
@pytest.mark.parametrize("character", [CHARGE_BEAM_CHARACTER, HYPERMODE_CHARACTER])
def test_beam_internals_lift_preserves_shell_and_other_animation_channels(game, character):
    rotation = [(1, 0, 0, 0)] * 2
    clip = Animation(
        1.0,
        (0.0, 1.0),
        {
            2: Track(rotation, [(0.1, 0.2, -0.471), (0.1, 0.2, -0.401)], None),
            3: Track(rotation, [(0, 0, 0), (0, 0, 0)], None),
        },
    )
    adjusted = align_pickup_internals(clip, character)
    assert adjusted.tracks[2].translation[0] == pytest.approx((0.1, 0.2, 0.0))
    assert adjusted.tracks[2].translation[1] == pytest.approx((0.1, 0.2, 0.07))
    assert adjusted.tracks[3] == clip.tracks[3]
    assert adjusted.tracks[2].rotation == clip.tracks[2].rotation
    assert clip.tracks[2].translation[0][2] == -0.471
    assert align_pickup_internals(clip, 123) is clip
    assert audit_compression(adjusted, game)["translation"] < 0.00001


@pytest.mark.parametrize("character", sorted(HYPER_BARE_CHARACTERS))
def test_bare_hyper_core_retains_source_proportions_at_canister_scale(character):
    from nullphaaze_crossgame.gc.corruption_model_scale import match_scale

    mesh = C(aabox=C(min=[-0.35] * 3, max=[0.35] * 3), attrib_arrays=C(positions=[[0.2, 0.1, 0.3]]))
    carrier = C(min=[-0.6, -0.65, -1.07], max=[0.6, 0.65, 1.07])
    result = fit_hyper_presentation(mesh, character, carrier)
    assert result.aabox == C(min=[-1.07] * 3, max=[1.07] * 3)
    assert result.attrib_arrays == mesh.attrib_arrays
    scale = match_scale([2.14] * 3, [1.3] * 3)[0]
    # A 0.7-unit ball remains an interior, rather than becoming a full-height pickup.
    assert 0.7 * scale < 1.3 * 0.34
    assert mesh.aabox.min == [-0.35] * 3
    assert fit_hyper_presentation(mesh, 123, carrier) is mesh


@pytest.mark.parametrize("game", [Game.PRIME, Game.ECHOES])
def test_boost_icon_rolls_with_parent_and_preserves_orbit_and_canister(game):
    rotation = [(1, 0, 0, 0), (0, 0, 1, 0)]
    clip = Animation(1, (0, 1), {i: Track(rotation, [(0.276, 0, 0.104)] * 2, None) for i in (2, 3, 4, 5)})
    adjusted = align_pickup_internals(clip, BOOST_BALL_CHARACTER)
    assert adjusted.tracks[5].rotation == [rotation[0], rotation[0]]
    assert adjusted.tracks[5].translation == clip.tracks[5].translation
    for bone in (2, 3, 4):
        assert adjusted.tracks[bone] == clip.tracks[bone]
    assert clip.tracks[5].rotation == rotation
    assert BOOST_TRAIL_BONE not in clip.tracks
    locator = adjusted.tracks[BOOST_TRAIL_BONE]
    assert locator.translation == clip.tracks[4].translation
    assert locator.rotation == [(1, 0, 0, 0)] * 2
    # The locator and ball centers stay coincident through the parent orbit,
    # including when the ball itself has rolled through 180 degrees.
    for frame in range(2):
        parent = adjusted.tracks[3].rotation[frame]
        assert rotate(parent, locator.translation[frame]) == rotate(parent, adjusted.tracks[4].translation[frame])
    assert audit_compression(adjusted, game)["rotation"] < math.radians(1)


def test_boost_trail_locator_inherits_orbit_but_not_ball_roll():
    def bone(i, parent):
        return C(
            id=i,
            parent_id=parent,
            position=[0, 0, 0],
            rotation=[1, 0, 0, 0],
            local_rotation=[1, 0, 0, 0],
            linked_bone_id_array=L([parent]),
        )

    skeleton = C(bones=L([bone(3, 1), bone(4, 3), bone(5, 4)]), build_order_id=L([5, 4, 3]), bone_names=L())
    result = prepare_pickup_skeleton(skeleton, BOOST_BALL_CHARACTER)
    locator = result.bones[-1]
    assert locator.id == BOOST_TRAIL_BONE
    assert locator.parent_id == 3
    assert locator.position == result.bones[1].position
    assert BOOST_TRAIL_BONE in result.bones[0].linked_bone_id_array
    assert result.bone_names[-1] == C(name=BOOST_TRAIL_NAME, bone_id=BOOST_TRAIL_BONE)
    assert result.build_order_id[0] == BOOST_TRAIL_BONE
    assert len(skeleton.bones) == 3
    assert prepare_pickup_skeleton(skeleton, 123) is skeleton


@pytest.mark.parametrize("game", [Game.PRIME, Game.ECHOES])
def test_hazard_fit_changes_only_interior_vertices(game):
    mesh, skin, skeleton = fixture_rig()
    skin.vertex_groups[0].weights_array[0].bone_id = 2
    skeleton.bones[0].id = 2
    mesh, encoded = reindex_mesh(mesh, skin, skeleton, game)
    adjusted = fit_pickup_internals(mesh, encoded, HAZARD_SHIELD_CHARACTER, game)
    assert adjusted.attrib_arrays.positions[0] == pytest.approx([v * 0.75 for v in mesh.attrib_arrays.positions[0]])
    assert adjusted.attrib_arrays.positions[1] == mesh.attrib_arrays.positions[1]
    assert adjusted.attrib_arrays.normals == mesh.attrib_arrays.normals
    assert adjusted.surfaces == mesh.surfaces
    assert fit_pickup_internals(mesh, encoded, 123, game) is mesh


@pytest.mark.parametrize("game", [Game.PRIME, Game.ECHOES])
@pytest.mark.parametrize("identity", [0x1122334455667788, *sorted(BOOST_TRAIL_EFFECTS)])
def test_particle_event_keeps_existing_particles_attached_to_bone(game, identity):
    from retro_data_structures.formats.evnt import ParticlePOINode

    event = C(
        base=C(
            unk_1=4,
            name="pickup glow",
            type=5,
            timestamp=C(time=0.0, differential_state=2),
            index=120,
            unk_2=0xFFFFFFFF,
            unique=0,
            weight=1.0,
            character_index=-1,
            flags=0x10,
            unk_extra=C(),
        ),
        duration=None,
        particle=C(type="PART", id=identity),
        bone_name=None,
        bone_id=None,
        effect_scale=None,
        transform_type=None,
        unk_float=0.75,
        unk_id=7,
    )
    converted = attached_particle_event(
        event, 123, 2, 2.0, {7: "spin_locator", BOOST_TRAIL_BONE: BOOST_TRAIL_NAME}, game, BOOST_BALL_CHARACTER
    )
    payload = ParticlePOINode.build(converted, target_game=game)
    actual = ParticlePOINode.parse(payload, target_game=game)
    assert actual.transform_type == 2
    assert actual.effect_scale == 0.75
    assert actual.particle.id == 123
    assert actual.base.flags == event.base.flags
    if game == Game.PRIME:
        assert actual.bone_name == (BOOST_TRAIL_NAME if identity in BOOST_TRAIL_EFFECTS else "spin_locator")
    else:
        assert actual.bone_id == (BOOST_TRAIL_BONE if identity in BOOST_TRAIL_EFFECTS else 7)
    assert event.transform_type is None
    assert event.particle.id == identity
    other_character = attached_particle_event(event, 123, 2, 2.0, {7: "spin_locator"}, game, 123)
    assert (other_character.bone_name if game == Game.PRIME else other_character.bone_id) == (
        "spin_locator" if game == Game.PRIME else 7
    )


@pytest.mark.parametrize("game", [Game.PRIME, Game.ECHOES])
def test_palette_duplicates_shared_attributes_per_weight_group(game):
    mesh, skin, skeleton = fixture_rig()
    result, payload = reindex_mesh(mesh, skin, skeleton, game)
    groups = Cskr.parse(payload, game).raw.vertex_groups
    assert [g.vertex_count for g in groups] == [1, 1]
    assert [g.weights_array[0].bone_id for g in groups] == ([3, 4] if game == Game.PRIME else [0, 1])
    vertices = result.surfaces[0].primitives[0].vertices
    assert [v.position for v in vertices] == [0, 1, 0]
    assert result.attrib_arrays.positions[0] == pytest.approx([1, -1, 0] if game == Game.PRIME else [2, 0, 0])
    assert result.attrib_arrays.normals[0] == pytest.approx([0, -1, 0] if game == Game.PRIME else [1, 0, 0])
    assert len(mesh.attrib_arrays.positions) == 1
    assert skin.vertex_groups[0].vertex_count == 99


@pytest.mark.parametrize("case", ["matrix", "palette", "attribute", "weights"])
def test_invalid_rig_rejected(case):
    mesh, skin, skeleton = fixture_rig()
    vertex = mesh.surfaces[0].primitives[0].vertices[0]
    if case == "matrix":
        vertex.matrix.position = -3
    elif case == "palette":
        skin.footer.pool_to_skin_idx[0] = -1
    elif case == "attribute":
        vertex.position = -1
    else:
        skin.vertex_groups[0].weights_array[0].weight = 0.5
    with pytest.raises(ValueError, match="matrix|palette|attribute|weight"):
        reindex_mesh(mesh, skin, skeleton, Game.PRIME)


def test_echoes_reindexed_palette_retains_surface_bank_and_source_slots():
    mesh, skin, skeleton = fixture_rig()
    mesh.surfaces[0].header.unk_1 = 1
    skin.footer.pool_to_skin_idx = L([65535] * 10 + [1, 0] + [65535] * 8)
    result, payload = reindex_mesh(mesh, skin, skeleton, Game.ECHOES, preserve_skin_matrices=True)
    parsed = Cskr.parse(payload, Game.ECHOES).raw
    assert result.surfaces[0].header.unk_1 == 1
    assert [v.matrix.position for v in result.surfaces[0].primitives[0].vertices] == [0, 3, 0]
    assert list(parsed.footer.pool_to_skin_idx) == [65535] * 10 + [1, 0] + [65535] * 8
