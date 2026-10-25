# Nullphaaze-CrossGame

Source-only model conversion work for Metroid Prime, Echoes and Corruption.
Includes Corruption-to-GameCube mesh, texture, rig, animation, particle and
sizing primitives; Prime/Echoes-to-Corruption conversion adapters; catalog
metadata; isolated static proof tools; and synthetic tests.

There is no CDV desktop application, GUI, generator, server, app build target or
retail model/texture/animation payload in this repository. Supply your own
supported game media. Converters retain their bounded format checks; the code
does not claim arbitrary model/shader conversion or exact Corruption shading.

## Related repositories

- [NullPhaaze](https://github.com/reedwhaley/NullPhaaze): standalone MIT patch core.
- [Nullphaaze-Multiworld](https://github.com/reedwhaley/Nullphaaze-Multiworld): GPL
  native runtime and reusable integration helpers.

The standalone GC primitives do not require either application frontend.
Corruption cache/archive adapters use the separate core and runtime helper
libraries, plus a compatible host's existing resource and serialization APIs.
Installing this package does not add cross-game options to the standalone core CLI.

## Install and test the standalone package

Use Python 3.12 in a virtual environment:

```sh
python -m pip install -c requirements.txt -e '.[test]'
nullphaaze-backport --help
python -m pytest tests --ignore=tests/host -q
```

`nullphaaze_crossgame.gc` contains the native GC conversion APIs. The built-in
`nullphaaze-backport` CLI is the earlier bounded rigid-pose Energy Tank / Hyper
Missile proof. Full character/animation/particle conversion APIs and the
30-entry Corruption GC catalog are retained separately for host integration;
the two-profile CLI is not advertised as a complete catalog exporter.

Example static asset conversion, using extracted files and a new output:

```sh
nullphaaze-backport --source CORRUPTION_DATA --prime PRIME_EXTRACT --target PRIME_EXTRACT --game prime --output NEW_PRIME_ASSETS
nullphaaze-backport --source CORRUPTION_DATA --prime PRIME_EXTRACT --target ECHOES_EXTRACT --game echoes --output NEW_ECHOES_ASSETS
```

Add `--item hyper-missile` for that proof profile. Original inputs remain external.
The optional static test-image builder is `tools/rigid_backport/build_proof.py`;
it consumes those assets and caller-supplied extracted files. These proof tools
are distinct from randomized exports and do not produce a desktop application.

## Host adapters and conversion into Corruption

`adapters/randovania/` retains cache/export integration functions, not a complete
host package. `adapters/nullphaaze_network/` retains model-specific conversion
helpers without duplicating native networking code. `scripts/_host.py` loads
these overlays in memory and aliases the standalone GC primitives for a
compatible host. It does not change host source files.

Using the compatible host environment's Python and separately obtained source
checkouts for the runtime library and core:

```sh
python scripts/prepare_corruption_models.py --host HOST_SOURCE --runtime MULTIWORLD_SOURCE --core CORE_SOURCE --corruption CORRUPTION_ISO --prime PRIME_ISO --echoes ECHOES_ISO --cache-root NEW_CACHE_ROOT
```

The host environment must already have its dependencies installed. The script
does not download or install a host application. The adapter validates disc
identities and source/cache hashes before conversion. Cached game resources
are generated locally and must never be committed or distributed with source.

To run synthetic host-adapter tests, set `NULLPHAAZE_CROSSGAME_HOST`,
`NULLPHAAZE_MULTIWORLD_SOURCE` and `NULLPHAAZE_CORE_SOURCE` to those source roots,
then run `python -m pytest tests/host -q`. In PowerShell use `$env:NAME='PATH'`.
These tests use synthetic or mocked inputs and do not require game media.

## Catalogs, provenance and acceptance

`nullphaaze_crossgame.catalog()` reads the packaged Prime/Echoes-to-Corruption
catalog. `catalog('corruption_gc_catalog')` reads the 30-entry GC source catalog.
Catalogs contain IDs, numeric presentation facts, dependency inventories and
hashes; geometry, textures, animations, sounds and test images are excluded.
`SOURCE.json` records source-file hashes and the limited packaging adaptations.

GPL-3.0-or-later; see `LICENSE` and retained source notices. Randomprime's MIT
catalog attribution is preserved in `src/nullphaaze_crossgame/data/randomprime-LICENSE.txt`.
This preserves the
separate core's MIT license. Automated source/synthetic tests are not new
visual, gameplay, save-durability or physical-hardware acceptance. Historical
local review receipts and private game outputs are not bundled.
