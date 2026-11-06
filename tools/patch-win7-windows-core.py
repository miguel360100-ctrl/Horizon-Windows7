from pathlib import Path
import os
import tarfile

VERSION = "0.62.2"
PACKAGE = f"windows-core-{VERSION}"
cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
registry = cargo_home / "registry"
source_dirs = sorted((registry / "src").glob(f"*/{PACKAGE}"))

if not source_dirs:
    archives = sorted((registry / "cache").glob(f"*/{PACKAGE}.crate"))
    if not archives:
        raise SystemExit(
            f"{PACKAGE}.crate was not fetched. Run cargo +nightly fetch first."
        )
    for archive in archives:
        source_root = registry / "src" / archive.parent.name
        source_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as crate:
            crate.extractall(source_root, filter="data")
        extracted = source_root / PACKAGE
        if extracted.is_dir():
            source_dirs.append(extracted)

if not source_dirs:
    raise SystemExit(f"Could not extract {PACKAGE} into Cargo's registry source cache.")

def patch_link(path: Path, function: str) -> None:
    content = path.read_text(encoding="utf-8")
    old = f'windows_link::link!("combase.dll" "system" fn {function}'
    new = f'windows_link::link!("ole32.dll" "system" fn {function}'
    if content.count(old) == 1:
        path.write_text(content.replace(old, new, 1), encoding="utf-8", newline="\n")
        print(f"{function}: combase.dll -> ole32.dll")
    elif content.count(new) == 1:
        print(f"{function}: already linked to ole32.dll")
    else:
        raise SystemExit(
            f"Expected exactly one COM binding for {function} in {path}; "
            "refusing to patch an unexpected windows-core version."
        )

for package_dir in source_dirs:
    manifest = package_dir / "Cargo.toml"
    if not manifest.is_file():
        raise SystemExit(f"Missing {manifest}; refusing to patch an unknown crate.")

    bindings = package_dir / "src/imp/bindings.rs"
    marshaler = package_dir / "src/imp/marshaler.rs"
    if not bindings.is_file() or not marshaler.is_file():
        raise SystemExit(f"Expected COM binding files are missing under {package_dir}")

    # These functions are exported by ole32.dll on Windows 7.
    patch_link(bindings, "CoTaskMemAlloc")
    patch_link(bindings, "CoTaskMemFree")
    patch_link(marshaler, "CoCreateFreeThreadedMarshaler")

    # CoIncrementMTAUsage is intentionally NOT redirected: it is not a Windows 7 API.
    remaining = bindings.read_text(encoding="utf-8")
    if 'windows_link::link!("combase.dll" "system" fn CoIncrementMTAUsage' not in remaining:
        raise SystemExit("The modern CoIncrementMTAUsage import was unexpectedly changed or removed.")

print(f"Verified targeted Windows 7 COM import patch in {PACKAGE}.")
