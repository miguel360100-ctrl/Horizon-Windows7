from pathlib import Path
import sys

source = Path(sys.argv[1])
text = source.read_text(encoding="utf-8")

old = '''    // The running file can be renamed but not deleted: it steps out of the folder into %TEMP%
    // (the same volume), and the next setup or uninstall clears it (`[`clean_temp`]`).
    if own.starts_with(&dir) {
        let aside = std::env::temp_dir().join(format!("{ASIDE_PREFIX}{}.exe", std::process::id()));
        if let Err(e) = fs::rename(&own, &aside) {
            left.push(format!("{}: {e}", own.display()));
        }
    }
'''

new = r'''    // Move the running image out of the install folder on the same volume. TEMP may
    // live on another drive, in which case fs::rename would fail with ERROR_NOT_SAME_DEVICE.
    // A tiny detached batch helper retries deletion after this process exits; this avoids
    // leaving a 45 MB renamed launcher beside the install directory.
    let own_parent = own.parent().unwrap_or_else(|| Path::new(""));
    let own_is_installed = match (own_parent.canonicalize(), dir.canonicalize()) {
        (Ok(own_parent), Ok(install_dir)) => same_path(&own_parent, &install_dir),
        _ => same_path(own_parent, &dir),
    };
    if own_is_installed {
        use std::os::windows::process::CommandExt as _;
        use std::process::Stdio;

        let aside_dir = dir.parent().unwrap_or_else(|| Path::new(""));
        let pid = std::process::id();
        let aside_name = format!("{ASIDE_PREFIX}{pid}.exe");
        let aside = aside_dir.join(&aside_name);
        if let Err(e) = fs::rename(&own, &aside) {
            left.push(format!("{}: {e}", own.display()));
        } else {
            // Use a fixed, generated basename and the install volume as the working
            // directory. No user-supplied path is interpolated into cmd.exe syntax.
            let helper_name = format!("{ASIDE_PREFIX}cleanup-{pid}.cmd");
            let helper = aside_dir.join(&helper_name);
            let log_name = format!("{ASIDE_PREFIX}cleanup-{pid}.log");
            let script = format!(
                "@echo off\r\nsetlocal\r\nset \"target={aside_name}\"\r\nset \"log={log_name}\"\r\nset /a attempts=0\r\n:retry\r\nif not exist \"%target%\" goto done\r\ndel /f /q \"%target%\" >nul 2>&1\r\nif not exist \"%target%\" goto done\r\nset /a attempts+=1\r\nif %attempts% GEQ 60 goto failed\r\nping 127.0.0.1 -n 2 >nul\r\ngoto retry\r\n:failed\r\necho Could not remove %target% after 60 attempts.>>\"%log%\"\r\n:done\r\ndel /f /q \"%~f0\" >nul 2>&1\r\n"
            );
            if let Err(e) = fs::write(&helper, script) {
                left.push(format!("{} (could not write cleanup helper): {e}", helper.display()));
            } else {
                let system_root = std::env::var_os("SystemRoot")
                    .unwrap_or_else(|| r"C:\Windows".into());
                let cmd = Path::new(&system_root).join("System32").join("cmd.exe");
                let cleanup = std::process::Command::new(cmd)
                    .args(["/D", "/C", &helper_name])
                    .current_dir(aside_dir)
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .creation_flags(0x00000008 | 0x08000000) // DETACHED_PROCESS | CREATE_NO_WINDOW
                    .spawn();
                if let Err(e) = cleanup {
                    left.push(format!("{} (cleanup helper could not start): {e}", helper.display()));
                }
            }
        }
    }
'''

if new.strip() in text:
    print("Windows 7 uninstaller retry-helper patch is already applied.")
    raise SystemExit(0)
count = text.count(old)
if count != 1:
    raise SystemExit(f"Expected one original uninstaller self-move block, found {count}")
text = text.replace(old, new, 1)
source.write_text(text, encoding="utf-8", newline="\n")
print("Patched uninstaller to rename on-volume and retry deletion from a detached helper.")
