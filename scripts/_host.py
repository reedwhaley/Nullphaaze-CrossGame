"""Load this repository's conversion adapters without changing host source."""
from pathlib import Path
import importlib
import sys
ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = ['corruption_animation', 'corruption_character', 'corruption_static_mesh', 'corruption_texture', 'corruption_particles', 'corruption_particle_curves', 'corruption_model_scale', 'corruption_file_provider', 'prime_pickup_dimensions']

def use_host(host, runtime=None, core=None):
    sys.dont_write_bytecode = True
    host = Path(host).resolve()
    source = host / "cdv" if (host / "cdv/randovania/__init__.py").is_file() else host
    if not (source / "randovania/__init__.py").is_file():
        raise ValueError("--host requires an existing compatible host checkout")
    dependencies = [str(Path(value).resolve() / "src") for value in (runtime, core) if value]
    sys.path[:0] = [str(ROOT / "src"), *dependencies, str(source)]
    host_module = importlib.import_module("randovania")
    if not Path(host_module.__file__).resolve().is_relative_to(source):
        raise ValueError("A different host is already imported")
    overlay = ROOT / "adapters"
    directories = {path.parent for path in overlay.rglob("*.py")}
    for directory in list(directories):
        directories.update(p for p in directory.parents if p.is_relative_to(overlay) and p != overlay)
    for directory in sorted(directories, key=lambda p: (len(p.parts), str(p))):
        name = directory.relative_to(overlay).as_posix().replace("/", ".")
        package = importlib.import_module(name)
        if str(directory) not in package.__path__:
            package.__path__.insert(0, str(directory))
    parent = importlib.import_module("randovania.patching.prime")
    for name in PRIMITIVES:
        module = importlib.import_module("nullphaaze_crossgame.gc." + name)
        sys.modules["randovania.patching.prime." + name] = module
        setattr(parent, name, module)
    return source
