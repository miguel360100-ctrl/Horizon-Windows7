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
    // %TEMP% can be on another volume, so keep the renamed image beside the install directory.
    // Delete it from a detached native command interpreter after this process exits.
    let own_parent = own.parent().unwrap_or_else(|| Path::new(""));
    let own_is_installed = match (own_parent.canonicalize(), dir.canonicalize()) {
        (Ok(own_parent), Ok(install_dir)) => same_path(&own_parent, &install_dir),
        _ => same_path(own_parent, &dir),
    };
    if own_is_installed {
        use std::os::windows::process::CommandExt as _;
        use std::process::Stdio;

        let aside_dir = dir.parent().unwrap_or_else(|| Path::new(""));
        let aside_name = format!("{ASIDE_PREFIX}{}.exe", std::process::id());
        let aside = aside_dir.join(&aside_name);
        if let Err(e) = fs::rename(&own, &aside) {
            left.push(format!("{}: {e}", own.display()));
        } else {
            // Run from the parent directory and pass only our generated ASCII filename.
            // This avoids cmd.exe quoting/expansion bugs with user paths containing spaces,
            // accents or percent signs. Retry because Windows releases the image lock on exit.
            let cleanup_command = format!(
                "for /L %i in (1,1,30) do (del /F /Q {aside_name} >NUL 2>&1 & if not exist {aside_name} exit /B 0 & ping 127.0.0.1 -n 2 >NUL)"
            );
            let cleanup = std::process::Command::new("cmd.exe")
                .args(["/D", "/C", cleanup_command.as_str()])
                .current_dir(aside_dir)
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
    print("Windows 7 uninstaller retry-helper patch is already applied.")
    raise SystemExit(0)
count = text.count(old)
if count != 1:
    raise SystemExit(f"Expected one original uninstaller self-move block, found {count}")
text = text.replace(old, new, 1)
source.write_text(text, encoding="utf-8", newline="\n")
print("Patched uninstaller to rename on-volume and retry deletion from a detached helper.")
