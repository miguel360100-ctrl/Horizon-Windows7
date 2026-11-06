"""Regression tests for the narrowly scoped Windows 7 COM/WinRT patch."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

PATCHER = Path(__file__).with_name("patch-win7-windows-core.py")
PACKAGE = "windows-core-0.62.2"

FACTORY_BLOCK = """        let mut get_com_factory = || {
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

class WindowsCorePatchTests(unittest.TestCase):
    def make_fake_cargo_home(self, root: Path, *, include_free: bool = True) -> Path:
        cargo_home = root / "cargo-home"
        package = cargo_home / "registry" / "src" / "test-registry" / PACKAGE
        bindings = package / "src" / "imp" / "bindings.rs"
        marshaler = package / "src" / "imp" / "marshaler.rs"
        factory_cache = package / "src" / "imp" / "factory_cache.rs"
        bindings.parent.mkdir(parents=True, exist_ok=True)
        (package / "Cargo.toml").write_text('[package]\nname = "windows-core"\n', encoding="utf-8")
        imports = [
            'windows_link::link!("combase.dll" "system" fn CoTaskMemAlloc(cb: usize) -> *mut core::ffi::c_void);',
            'windows_link::link!("combase.dll" "system" fn CoIncrementMTAUsage(cookie: *mut *mut core::ffi::c_void) -> i32);',
            'windows_link::link!("api-ms-win-core-winrt-l1-1-0.dll" "system" fn RoGetActivationFactory(name: *mut core::ffi::c_void, iid: *const core::ffi::c_void, factory: *mut *mut core::ffi::c_void) -> i32);',
        ]
        if include_free:
            imports.append('windows_link::link!("combase.dll" "system" fn CoTaskMemFree(pv: *const core::ffi::c_void);')
        bindings.write_text("\n".join(imports) + "\n", encoding="utf-8")
        marshaler.write_text(
            'windows_link::link!("combase.dll" "system" fn CoCreateFreeThreadedMarshaler(outer: *mut core::ffi::c_void, result: *mut *mut core::ffi::c_void) -> i32);\n',
            encoding="utf-8",
        )
        factory_cache.write_text(
            "use super::*;\n" + FACTORY_BLOCK + "\n"
            + "    type DllGetActivationFactory =\n        extern \"system\" fn(name: *mut c_void, factory: *mut *mut c_void) -> crate::HRESULT;\n",
            encoding="utf-8",
        )
        return cargo_home

    def run_patcher(self, cargo_home: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CARGO_HOME"] = str(cargo_home)
        return subprocess.run([sys.executable, str(PATCHER)], env=env, text=True, capture_output=True, check=False)

    def test_redirects_legacy_exports_and_dynamically_resolves_winrt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cargo_home = self.make_fake_cargo_home(Path(temporary))
            first = self.run_patcher(cargo_home)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            package = cargo_home / "registry" / "src" / "test-registry" / PACKAGE
            bindings = (package / "src" / "imp" / "bindings.rs").read_text(encoding="utf-8")
            marshaler = (package / "src" / "imp" / "marshaler.rs").read_text(encoding="utf-8")
            factory = (package / "src" / "imp" / "factory_cache.rs").read_text(encoding="utf-8")
            self.assertIn('link!("ole32.dll" "system" fn CoTaskMemAlloc', bindings)
            self.assertIn('link!("ole32.dll" "system" fn CoTaskMemFree', bindings)
            self.assertIn('link!("ole32.dll" "system" fn CoCreateFreeThreadedMarshaler', marshaler)
            self.assertNotIn("CoIncrementMTAUsage", bindings)
            self.assertNotIn("RoGetActivationFactory", bindings)
            self.assertIn('delay_load::<RoGetActivationFactory>', factory)
            self.assertIn('delay_load::<CoIncrementMTAUsage>', factory)
            self.assertNotIn("CoIncrementMTAUsage(&mut cookie)", factory)
            second = self.run_patcher(cargo_home)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_patches_unindented_windows_core_macro_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cargo_home = self.make_fake_cargo_home(Path(temporary))
            package = cargo_home / "registry" / "src" / "test-registry" / PACKAGE
            bindings = package / "src" / "imp" / "bindings.rs"
            source = bindings.read_text(encoding="utf-8")
            source = source.replace("windows_link::link!", "windows_core::link!")
            bindings.write_text(source, encoding="utf-8")
            result = self.run_patcher(cargo_home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            patched = bindings.read_text(encoding="utf-8")
            self.assertIn('windows_core::link!("ole32.dll" "system" fn CoTaskMemAlloc', patched)
            self.assertNotIn('windows_core::link!("combase.dll" "system" fn CoTaskMemAlloc', patched)

    def test_refuses_unexpected_windows_core_source_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cargo_home = self.make_fake_cargo_home(Path(temporary), include_free=False)
            result = self.run_patcher(cargo_home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CoTaskMemFree", result.stderr)

if __name__ == "__main__":
    unittest.main()
