"""Import newly added URLs without ever changing an existing clip's numeric slot."""

import argparse
from catalog import REGISTRY_PATH, import_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="UTF-8 text file containing one YouTube URL per line")
    parser.add_argument("--registry", default=str(REGISTRY_PATH), help="Registry to append to (default: clips.json)")
    args = parser.parse_args()
    try:
        added, count = import_file(args.source, args.registry)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Import failed: {error}\n")
    print(f"Added {added} clip(s); {count} stable slots. Existing slots retained.")


if __name__ == "__main__":
    main()
