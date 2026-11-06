from pathlib import Path
import os
import sys
import tarfile

VERSION = "0.62.2"
PACKAGE = f"windows-core-{VERSION}"
FILES = (
    Path("src/imp/bindings.rs"),
    Path("src/imp/marshaler.rs"),
)

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
        index_name = archive.parent.name
        source_root = registry / "src" / index_name
        source_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as crate:
            crate.extractall(source_root, filter="data")
        extracted = source_root / PACKAGE
        if extracted.is_dir():
            source_dirs.append(extracted)

if not source_dirs:
    raise SystemExit(f"Could not extract {PACKAGE} into Cargo's registry source cache.")

patched = []
for package_dir in source_dirs:
    manifest = package_dir / "Cargo.toml"
    if not manifest.is_file():
        raise SystemExit(f"Missing {manifest}; refusing to patch an unknown crate.")
    for relative in FILES:
        path = package_dir / relative
        if not path.is_file():
            raise SystemExit(f"Expected Windows 7 COM binding file not found: {path}")
        content = path.read_text(encoding="utf-8")
        occurrences = content.count('"combase.dll"')
        if occurrences:
            content = content.replace('"combase.dll"', '"ole32.dll"')
            path.write_text(content, encoding="utf-8", newline="\n")
            patched.append((str(path), occurrences))
        elif '"ole32.dll"' in content:
            # The patch is deliberately idempotent for repeated workflow runs.
            continue
        else:
            raise SystemExit(
                f"{path} contains neither the expected combase.dll import nor the "
                "already-patched ole32.dll import."
            )

if not patched:
    # A cached package may already have been patched by a previous local run.
    # Verify the intended functions are in the files before accepting it.
    bindings = (source_dirs[0] / FILES[0]).read_text(encoding="utf-8")
    marshaler = (source_dirs[0] / FILES[1]).read_text(encoding="utf-8")
    if "CoTaskMemFree" not in bindings or "CoCreateFreeThreadedMarshaler" not in marshaler:
        raise SystemExit("The expected Windows COM functions were not found in windows-core.")
    if '"combase.dll"' in bindings or '"combase.dll"' in marshaler:
        raise SystemExit("A Windows 7-incompatible combase.dll reference remains.")
    print(f"{PACKAGE} already has the Win7 ole32.dll compatibility patch.")
else:
    for path, count in patched:
        print(f"Repointed {count} COM import(s) to ole32.dll in {path}")
    print(f"Patched {PACKAGE} for the Windows 7 COM runtime.")
