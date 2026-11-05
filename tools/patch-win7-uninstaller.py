from pathlib import Path
import sys

source = Path(sys.argv[1])
text = source.read_text(encoding="utf-8")

old = '''    // The running file can be renamed but not deleted: it steps out of the folder into %TEMP%
    // (the same volume), and the next setup or uninstall clears it ([`clean_temp`]).
    if own.starts_with(&dir) {
        let aside = std::env::temp_dir().join(format!("{ASIDE_PREFIX}{}.exe", std::process::id()));
        if let Err(e) = fs::rename(&own, &aside) {
            left.push(format!("{}: {e}", own.display()));
        }
    }
'''

new = r'''    // The running executable must leave the install folder before that folder can be removed.
    // `%TEMP%` can be on another volume (for example, a portable install on D: with TEMP on C:),
    // and `rename` across volumes fails with ERROR_NOT_SAME_DEVICE. Use the install folder's
    // parent, which is on the same volume, then ask a detached cmd.exe to delete the renamed image
    // after this process exits. This keeps uninstall per-user and does not require elevation.
    let own_parent = own.parent().unwrap_or_else(|| Path::new(""));
    let own_is_installed = match (own_parent.canonicalize(), dir.canonicalize()) {
        (Ok(own_parent), Ok(install_dir)) => same_path(&own_parent, &install_dir),
        _ => same_path(own_parent, &dir),
    };
    if own_is_installed {
        use std::os::windows::process::CommandExt as _;
        use std::process::Stdio;

        let aside_dir = dir.parent().unwrap_or_else(|| Path::new(""));
        let aside = aside_dir.join(format!("{ASIDE_PREFIX}{}.exe", std::process::id()));
        if let Err(e) = fs::rename(&own, &aside) {
            left.push(format!("{}: {e}", own.display()));
        } else {
            // Environment-variable expansion avoids interpolating a user-controlled path into
            // cmd.exe syntax. The path is still quoted so spaces and shell metacharacters are safe.
            let cleanup = std::process::Command::new("cmd.exe")
                .args([
                    "/D",
                    "/C",
                    "ping 127.0.0.1 -n 4 >NUL & del /F /Q \"%HORIZON_UNINSTALL_EXE%\"",
                ])
                .env("HORIZON_UNINSTALL_EXE", &aside)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .creation_flags(0x00000008 | 0x08000000) // DETACHED_PROCESS | CREATE_NO_WINDOW
                .spawn();
            if let Err(e) = cleanup {
                left.push(format!("{} (scheduled cleanup could not start): {e}", aside.display()));
            }
        }
    }
'''

if new.strip() in text:
    print("Windows 7 uninstaller cleanup patch is already applied.")
    raise SystemExit(0)
count = text.count(old)
if count != 1:
    raise SystemExit(f"Expected one original uninstaller self-move block, found {count}")
text = text.replace(old, new, 1)
source.write_text(text, encoding="utf-8", newline="\n")
print("Patched uninstall self-move to stay on the install volume and clean up after process exit.")
