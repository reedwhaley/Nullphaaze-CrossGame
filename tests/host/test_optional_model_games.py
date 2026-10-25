import copy
from pathlib import Path
from unittest.mock import Mock

import pytest

from nullphaaze_network.prime3_lua_service.multiworld_models import patch_archives, presentation_plan
from randovania.patching.prime.corruption_models import prepare_cache


@pytest.mark.parametrize('enabled', [frozenset(), frozenset({'prime1'}), frozenset({'prime2'}), frozenset({'prime1', 'prime2'})])
def test_presentation_choice_preserves_placement_and_recipient_data(enabled):
    plan = [{'index': i, 'game': game, 'name': name, 'recipient': 'other player'}
            for i, (game, name) in enumerate([('prime1', 'Ice Beam'), ('prime2', 'Dark Beam'), ('prime3', 'Missile')])]
    before = copy.deepcopy(plan)
    result = presentation_plan(plan, enabled)
    assert plan == before
    assert [r['game'] for r in result] == [r['game'] if r['game'] in enabled else 'prime3' for r in plan]
    for a, b in zip(plan, result, strict=True):
        assert {k:v for k,v in a.items() if k!='game'} == {k:v for k,v in b.items() if k!='game'}


def test_disabled_imports_do_not_read_sources_cache_or_archives(tmp_path):
    assert prepare_cache(None, None, Path('missing-corruption.iso'), tmp_path / 'cache', Mock()) is None
    plan = [{'index': i, 'game': 'prime1' if i%2 else 'prime2', 'name':'Energy Tank'} for i in range(100)]
    report = patch_archives(Path('missing-source'), tmp_path / 'output', plan, Path('missing-cache'), enabled_games=frozenset())
    assert report['actors'] == 0 and report['native_fallback_locations'] == 100
    assert not list(tmp_path.iterdir())


def test_unknown_game_selection_fails_explicitly():
    with pytest.raises(ValueError, match='Unknown imported model game'):
        presentation_plan([], {'invalid'})
