"""Run the Prime/Echoes-to-Corruption cache adapter with an explicit host."""
import argparse
from pathlib import Path
from _host import use_host

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", required=True, type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--core", type=Path)
    args, remaining = parser.parse_known_args()
    use_host(args.host, args.runtime, args.core)
    from randovania.patching.prime.corruption_models import main as prepare
    return prepare(remaining)

if __name__ == "__main__":
    raise SystemExit(main())
