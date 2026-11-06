from pathlib import Path
import os
import re
import tarfile

VERSION = "0.62.2"
PACKAGE = f"windows-core-{VERSION}"
cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
registry = cargo_home / "registry"
source_dirs = sorted((registry / "src").glob(f"*/{PACKAGE}"))

if not source_dirs:
    archives = sorted((registry / "cache").glob(f"*/{PACKAGE}.crate"))
    if not archives:
        raise SystemExit(f"{PACKAGE}.crate was not fetched. Run cargo +nightly fetch first.")
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
    lines = content.splitlines(keepends=True)
    target = [
        i for i, line in enumerate(lines)
        if "::link!(" in line
        and '"combase.dll"' in line
        and re.search(rf"\bfn\s+{re.escape(function)}\b", line)
    ]
    if len(target) == 1:
        i = target[0]
        lines[i] = lines[i].replace('"combase.dll"', '"ole32.dll"', 1)
        path.write_text("".join(lines), encoding="utf-8", newline="\n")
        print(f"{function}: combase.dll -> ole32.dll")
    elif len(target) == 0:
        already = [
            line for line in lines
            if "::link!(" in line
            and '"ole32.dll"' in line
            and re.search(rf"\bfn\s+{re.escape(function)}\b", line)
        ]
        if len(already) == 1:
            print(f"{function}: already linked to ole32.dll")
        else:
            raise SystemExit(f"Expected exactly one COM binding for {function} in {path}; refusing unexpected source.")
    else:
        raise SystemExit(f"Found {len(target)} COM bindings for {function} in {path}; refusing ambiguous source.")

def remove_import(path: Path, function: str) -> None:
    content = path.read_text(encoding="utf-8")
    pattern = rf'(?m)^[ \t]*(?:windows_link|windows_core)::link!\("[^"]+"[ \t]+"system"[ \t]+fn[ \t]+{re.escape(function)}\([^\n]*\);[ \t]*\n'
    updated, removed = re.subn(pattern, "", content)
    if removed == 1:
        path.write_text(updated, encoding="utf-8", newline="\n")
        print(f"{function}: removed unsupported static import")
    elif removed == 0 and re.search(rf'\bfn\s+{re.escape(function)}\b', content):
        raise SystemExit(f"Found unexpected {function} declaration; refusing to patch.")
    elif removed > 1:
        raise SystemExit(f"Found multiple {function} declarations; refusing to patch.")
    else:
        print(f"{function}: static import already absent")

def patch_factory_cache(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    old = """    let mut get_com_factory = || {
        crate::HRESULT(RoGetActivationFactory(
            transmute_copy(&name),
            &I::IID as *const _ as _,
            &mut factory as *mut _ as *mut _,
        ))
    };
    let mut code = get_com_factory();

    // If RoGetActivationFactory fails because combase hasn't been loaded yet then load combase
    // automatically so that it "just works" for apartment-agnostic code.
    if code == CO_E_NOTINITIALIZED {
        let mut cookie = core::ptr::null_mut();
        CoIncrementMTAUsage(&mut cookie);

        // Now try a second time to get the activation factory via the OS.
        code = get_com_factory();
    }"""
    # The closure is nested inside the unsafe factory-loading block in the
    # published 0.62.2 source, so its indentation is four spaces deeper than
    # the compact regression fixture above.
    old = "\n".join(("    " + line if line else line) for line in old.split("\n"))
    new = """            let mut get_com_factory = || {
                // WinRT activation is unavailable on Windows 7. Resolve the API
                // dynamically so the binary has no static WinRT API-set import.
                let function = delay_load::<RoGetActivationFactory>(
                    crate::s!("api-ms-win-core-winrt-l1-1-0.dll"),
                    crate::s!("RoGetActivationFactory"),
                );
                match function {
                    Some(function) => crate::HRESULT(function(
                        transmute_copy(&name),
                        &I::IID as *const _ as *const c_void,
                        &mut factory as *mut _ as *mut _,
                    )),
                    None => crate::HRESULT(0x80004001u32 as i32), // E_NOTIMPL
                }
            };
            let mut code = get_com_factory();

            // Keep the modern Windows behavior without a static import: on
            // Windows 8+, dynamically resolve the MTA helper from ole32.dll.
            if code == CO_E_NOTINITIALIZED {
                let mut cookie = core::ptr::null_mut();
                if let Some(increment) = delay_load::<CoIncrementMTAUsage>(
                    crate::s!("ole32.dll"),
                    crate::s!("CoIncrementMTAUsage"),
                ) {
                    increment(&mut cookie);
                    code = get_com_factory();
                }
            }"""
    if content.count(old) == 1:
        content = content.replace(old, new, 1)
        print("factory_cache.rs: WinRT and MTA APIs now resolve dynamically")
    elif content.count("delay_load::<RoGetActivationFactory>") == 1 and "delay_load::<CoIncrementMTAUsage>" in content:
        print("factory_cache.rs: dynamic WinRT/MTA resolution already applied")
    else:
        raise SystemExit(f"Expected exact windows-core {VERSION} factory_cache block in {path}; refusing unexpected source.")
    aliases = """type RoGetActivationFactory = extern "system" fn(
    name: *mut c_void,
    iid: *const c_void,
    factory: *mut *mut c_void,
) -> i32;
type CoIncrementMTAUsage = extern "system" fn(cookie: *mut *mut c_void) -> i32;

"""
    aliases_present = (
        "type RoGetActivationFactory =" in content
        and "type CoIncrementMTAUsage =" in content
    )
    if not aliases_present:
        marker = "use super::*;\n"
        position = content.find(marker)
        if position < 0:
            raise SystemExit("Could not locate factory_cache module imports for function-pointer aliases.")
        position += len(marker)
        content = content[:position] + aliases + content[position:]
    path.write_text(content, encoding="utf-8", newline="\n")

def patch_windows_sys_task_mem_free() -> None:
    # windows-sys 0.61+ independently moved this legacy Win32 API to
    # combase.dll. Windows 7 exports the same API from ole32.dll.
    packages = sorted((registry / "src").glob("*/windows-sys-*"))
    patched = 0
    for package in packages:
        if not (package / "Cargo.toml").is_file():
            continue
        for path in sorted((package / "src").rglob("*.rs")):
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            targets = [
                i for i, line in enumerate(lines)
                if "::link!(" in line and '"combase.dll"' in line
                and re.search(r"\\bfn\\s+CoTaskMemFree\\b", line)
            ]
            if len(targets) > 1:
                raise SystemExit(f"Found ambiguous CoTaskMemFree bindings in {path}")
            if targets:
                i = targets[0]
                lines[i] = lines[i].replace('"combase.dll"', '"ole32.dll"', 1)
                path.write_text("".join(lines), encoding="utf-8", newline="\\n")
                patched += 1
                print(f"{package.name}/{path.name}: CoTaskMemFree combase.dll -> ole32.dll")
    if patched == 0:
        raise SystemExit("Could not find the expected windows-sys CoTaskMemFree combase.dll binding.")
    print(f"Patched {patched} windows-sys CoTaskMemFree binding(s) for Windows 7.")

for package_dir in source_dirs:
    if not (package_dir / "Cargo.toml").is_file():
        raise SystemExit(f"Missing Cargo.toml under {package_dir}; refusing unknown crate.")
    bindings = package_dir / "src/imp/bindings.rs"
    marshaler = package_dir / "src/imp/marshaler.rs"
    factory_cache = package_dir / "src/imp/factory_cache.rs"
    if not all(path.is_file() for path in (bindings, marshaler, factory_cache)):
        raise SystemExit(f"Expected COM source files are missing under {package_dir}")

    patch_link(bindings, "CoTaskMemAlloc")
    patch_link(bindings, "CoTaskMemFree")
    patch_link(marshaler, "CoCreateFreeThreadedMarshaler")

    # Both APIs are unavailable on Windows 7. Their uses are dynamically
    # resolved in factory_cache.rs, so neither can remain a static import.
    remove_import(bindings, "CoIncrementMTAUsage")
    remove_import(bindings, "RoGetActivationFactory")
    patch_factory_cache(factory_cache)

print(f"Verified targeted Windows 7 COM/WinRT compatibility patch in {PACKAGE}.")

patch_windows_sys_task_mem_free()
