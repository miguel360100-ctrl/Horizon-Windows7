"""Regression tests for the narrowly scoped Windows 7 COM import patch."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


PATCHER = Path(__file__).with_name("patch-win7-windows-core.py")
PACKAGE = "windows-core-0.62.2"


class WindowsCorePatchTests(unittest.TestCase):
    def make_fake_cargo_home(self, root: Path, *, include_free: bool = True) -> Path:
        cargo_home = root / "cargo-home"
        package = cargo_home / "registry" / "src" / "test-registry" / PACKAGE
        bindings = package / "src" / "imp" / "bindings.rs"
        marshaler = package / "src" / "imp" / "marshaler.rs"
        bindings.parent.mkdir(parents=True, exist_ok=True)
        marshaler.parent.mkdir(parents=True, exist_ok=True)
        (package / "Cargo.toml").write_text('[package]\nname = "windows-core"\n', encoding="utf-8")

        imports = [
            'windows_link::link!("combase.dll" "system" fn CoTaskMemAlloc(cb: usize) -> *mut core::ffi::c_void);',
        ]
        if include_free:
            imports.append(
                'windows_link::link!("combase.dll" "system" fn CoTaskMemFree(pv: *const core::ffi::c_void);'
            )
        imports.append(
            'windows_link::link!("combase.dll" "system" fn CoIncrementMTAUsage(cookie: *mut core::ffi::c_void) -> i32);'
        )
        bindings.write_text("\n".join(imports) + "\n", encoding="utf-8")
        marshaler.write_text(
            'windows_link::link!("combase.dll" "system" fn CoCreateFreeThreadedMarshaler(outer: *mut core::ffi::c_void, result: *mut *mut core::ffi::c_void) -> i32);\n',
            encoding="utf-8",
        )
        return cargo_home

    def run_patcher(self, cargo_home: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CARGO_HOME"] = str(cargo_home)
        return subprocess.run(
            [sys.executable, str(PATCHER)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_redirects_only_the_three_legacy_com_exports_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cargo_home = self.make_fake_cargo_home(Path(temporary))
            first = self.run_patcher(cargo_home)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            package = cargo_home / "registry" / "src" / "test-registry" / PACKAGE
            bindings = (package / "src" / "imp" / "bindings.rs").read_text(encoding="utf-8")
            marshaler = (package / "src" / "imp" / "marshaler.rs").read_text(encoding="utf-8")

            self.assertIn('link!("ole32.dll" "system" fn CoTaskMemAlloc', bindings)
            self.assertIn('link!("ole32.dll" "system" fn CoTaskMemFree', bindings)
            self.assertIn('link!("ole32.dll" "system" fn CoCreateFreeThreadedMarshaler', marshaler)
            self.assertNotIn("CoIncrementMTAUsage", bindings)

            second = self.run_patcher(cargo_home)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("already linked to ole32.dll", second.stdout)
            self.assertNotIn("CoIncrementMTAUsage", (package / "src" / "imp" / "bindings.rs").read_text(encoding="utf-8"))

    def test_refuses_an_unexpected_windows_core_source_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cargo_home = self.make_fake_cargo_home(Path(temporary), include_free=False)
            result = self.run_patcher(cargo_home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CoTaskMemFree", result.stderr)


if __name__ == "__main__":
    unittest.main()
