import json
from pathlib import Path

import pytest

from randovania.patching.prime import corruption_models as models


@pytest.mark.parametrize('header', [b'', b'G2ME01', b'RM3E01', b'not an image'])
def test_wrong_source_images_rejected_before_conversion(tmp_path, header):
    source = tmp_path / 'wrong.iso'
    source.write_bytes(header)
    with pytest.raises(ValueError, match='not Metroid Prime'):
        models.validate_image(source, b'GM8', 'Metroid Prime')
    assert source.read_bytes() == header


def fake_inputs(tmp_path, monkeypatch):
    paths = [tmp_path / f'{name}.iso' for name in ('prime', 'echoes', 'corruption')]
    for index, path in enumerate(paths):
        path.write_bytes(bytes([index]))
    monkeypatch.setattr(models, 'validate_image', lambda *args: None)
    monkeypatch.setattr(models, 'catalog', lambda: {'expected_files': {'test.TXTR': 'hash'}})
    monkeypatch.setattr(models, 'ModelCache', lambda path: None)
    return paths


def fake_build(*args):
    stage = args[3]
    (stage / 'assets').mkdir(parents=True)
    (stage / 'assets/test.TXTR').write_bytes(b'local converted asset')
    manifest = {'files': {'test.TXTR': 'hash'}}
    (stage / 'models.json').write_text(json.dumps(manifest))
    return manifest


def test_source_bound_cache_reuses_verified_output(tmp_path, monkeypatch):
    paths = fake_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(models, 'build_cache', fake_build)
    root = tmp_path / 'caches'
    first = models.prepare_cache(*paths, root, lambda *args: None)
    monkeypatch.setattr(models, 'build_cache', lambda *args: pytest.fail('Cache was rebuilt'))
    assert models.prepare_cache(*paths, root, lambda *args: None) == first
    assert len(list(root.iterdir())) == 1
    # Changing a bound source is not allowed to reuse the previous cache.
    paths[0].write_bytes(b'changed')
    with pytest.raises(pytest.fail.Exception, match='Cache was rebuilt'):
        models.prepare_cache(*paths, root, lambda *args: None)
    assert first.is_dir()


def test_failed_preparation_preserves_existing_cache_and_sources(tmp_path, monkeypatch):
    paths = fake_inputs(tmp_path, monkeypatch)
    root = tmp_path / 'caches'
    protected = root / 'previous/assets'
    protected.mkdir(parents=True)
    (protected / 'preserve').write_bytes(b'previous cache')
    before = [path.read_bytes() for path in paths]

    def fail(*args):
        fake_build(*args)
        raise ValueError('Unsupported model')

    monkeypatch.setattr(models, 'build_cache', fail)
    with pytest.raises(ValueError, match='Unsupported model'):
        models.prepare_cache(*paths, root, lambda *args: None)
    assert list(root.iterdir()) == [root / 'previous']
    assert (protected / 'preserve').read_bytes() == b'previous cache'
    assert [path.read_bytes() for path in paths] == before


def test_changed_source_during_build_is_not_published(tmp_path, monkeypatch):
    paths = fake_inputs(tmp_path, monkeypatch)

    def changed(*args):
        manifest = fake_build(*args)
        paths[1].write_bytes(b'changed while reading')
        return manifest

    monkeypatch.setattr(models, 'build_cache', changed)
    root = tmp_path / 'caches'
    with pytest.raises(ValueError, match='source image changed'):
        models.prepare_cache(*paths, root, lambda *args: None)
    assert list(root.iterdir()) == []


def test_cache_identity_conflict_stops_without_overwrite(tmp_path, monkeypatch):
    paths = fake_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(models, 'build_cache', fake_build)
    root = tmp_path / 'caches'
    first = models.prepare_cache(*paths, root, lambda *args: None)
    manifest = first / 'models.json'
    value = json.loads(manifest.read_text())
    value['source_images']['echoes'] = 'conflicting-image'
    manifest.write_text(json.dumps(value))
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match='provenance mismatch'):
        models.prepare_cache(*paths, root, lambda *args: None)
    assert manifest.read_bytes() == before


def test_platform_roundoff_is_canonical_but_geometry_changes_are_rejected(monkeypatch):
    reference = {'center': [0., 0., 1.], 'scale': .5, 'bounds': [[-1., -1., 0.], [1., 1., 2.]]}
    monkeypatch.setattr(models, 'catalog', lambda: {'presentation': {'Echoes:Test': reference}})
    center = [1e-16, -1e-16, 1.]
    bounds = [[-1., -1., 0.], [1., 1., 2.]]
    row = {'game': 'Echoes', 'name': 'Test'}
    models.canonicalize_bounds(row, .5, center, bounds)
    assert center == [0., 0., 1.]
    with pytest.raises(ValueError, match='pose bounds differ'):
        models.canonicalize_bounds(row, .5, [.001, 0., 1.], bounds)
    with pytest.raises(ValueError, match='pose bounds differ'):
        models.canonicalize_bounds(row, .6, center, bounds)
    with pytest.raises(ValueError, match='pose bounds differ'):
        models.canonicalize_bounds(row, .5, [float('nan'), 0., 1.], bounds)
