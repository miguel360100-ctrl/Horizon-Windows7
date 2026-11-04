from pathlib import Path
import sys

source = Path(sys.argv[1])
text = source.read_text(encoding="utf-8")

def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source match, found {count}")
    text = text.replace(old, new, 1)

replace_once(
'''    let program = read_program(path, &file)?;
    if !is_game(&program) {
        return Err(not_a_game(&file));
    }
    let selected = backend::Settings::load().selected;
    let base = base_for(&backend::installed(), requested, selected.as_deref())?;
    let date = chrono::Local::now().format("%Y-%m-%d").to_string();
    let tag = install_in(&backend::version_dir(""), &base, &program, &file, &date)?;
''',
'''    let program = read_program(path, &file)?;
    if !is_game(&program) {
        return Err(not_a_game(&file));
    }
    // Complete Win7 archives carry their companion tools and matching official base.
    // Plain EXE imports remain compatible with the original import flow.
    let extras = read_package_extras(path, &file)?;
    let selected = backend::Settings::load().selected;
    if let (Some(requested), Some(package_base)) = (requested, extras.base.as_deref()) {
        if requested != package_base {
            return Err(format!(
                "This Windows 7 build was compiled for {package_base}, not {requested}. Install and select {package_base} before importing it."
            ));
        }
    }
    let requested_base = requested.or(extras.base.as_deref());
    let base = base_for(&backend::installed(), requested_base, selected.as_deref())?;
    let date = chrono::Local::now().format("%Y-%m-%d").to_string();
    let tag = install_in_with_extras(
        &backend::version_dir(""),
        &base,
        &program,
        &file,
        &date,
        &extras,
    )?;
''',
"import flow",
)

anchor = '''fn holds_no_game(file: &str) -> String {'''
extras = r'''
/// Extra files carried by a complete Windows-compatible game import.
#[derive(Clone, Debug, Default)]
struct PackageExtras {
    base: Option<String>,
    helpers: Vec<(String, Vec<u8>)>,
}

const PACKAGE_METADATA: &str = "horizon-win7-build.json";
const PACKAGE_BASE: &str = "nightly-2026-11-03";
const PACKAGE_SOURCE_COMMIT: &str = "294448014fba585f8d5d09dd8886f482493b6417";
const PACKAGE_TARGET: &str = "x86_64-win7-windows-msvc";
const COMPANION_BASES: [&str; 3] = ["horizon-ctl", "horizon-prepare", "horizon-server"];

fn companion_names() -> Vec<String> {
    COMPANION_BASES
        .iter()
        .map(|name| format!("{name}{}", std::env::consts::EXE_SUFFIX))
        .collect()
}

/// Reads the companion executables and optional base tag from a ZIP, including a
/// GitHub Actions artifact ZIP containing the actual game archive.
fn read_package_extras(path: &Path, file: &str) -> Result<PackageExtras, String> {
    if !file.to_ascii_lowercase().ends_with(".zip") {
        return Ok(PackageExtras::default());
    }
    let archive = fs::File::open(path).map_err(|e| format!("{file}: {e}"))?;
    let zip = zip::ZipArchive::new(archive).map_err(|e| format!("{file}: {e}"))?;
    extras_from_zip(zip, file, true)
}

fn extras_from_zip<R: Read + Seek>(
    mut zip: zip::ZipArchive<R>,
    file: &str,
    nested: bool,
) -> Result<PackageExtras, String> {
    let names = companion_names();
    let mut extras = PackageExtras::default();
    let mut inner = None;
    for i in 0..zip.len() {
        let entry = zip.by_index(i).map_err(|e| format!("{file}: {e}"))?;
        let name = entry
            .enclosed_name()
            .and_then(|p| Some(p.file_name()?.to_string_lossy().into_owned()))
            .unwrap_or_default();
        if !entry.is_file() {
            continue;
        }
        if names.iter().any(|expected| expected == &name) {
            if extras.helpers.iter().any(|(found, _)| found == &name) {
                return Err(format!("{file}: duplicate companion executable {name}"));
            }
            extras.helpers.push((name, read_at_most(entry, file)?));
        } else if name == PACKAGE_METADATA {
            if extras.base.is_some() {
                return Err(format!("{file}: duplicate {PACKAGE_METADATA}"));
            }
            let bytes = read_at_most(entry, file)?;
            if bytes.len() > 16 * 1024 {
                return Err(format!("{file}: {PACKAGE_METADATA} is too large"));
            }
            let metadata: serde_json::Value = serde_json::from_slice(&bytes)
                .map_err(|e| format!("{file}: invalid {PACKAGE_METADATA}: {e}"))?;
            if metadata["schema"].as_u64() != Some(1) {
                return Err(format!("{file}: unsupported {PACKAGE_METADATA} schema"));
            }
            if metadata["base"].as_str() != Some(PACKAGE_BASE)
                || metadata["source_commit"].as_str() != Some(PACKAGE_SOURCE_COMMIT)
                || metadata["target"].as_str() != Some(PACKAGE_TARGET)
            {
                return Err(format!(
                    "{file}: {PACKAGE_METADATA} does not match the pinned Windows 7 game build"
                ));
            }
            extras.base = Some(PACKAGE_BASE.to_owned());
        } else if nested
            && inner.is_none()
            && [".zip", ".tar.gz", ".tgz"]
                .iter()
                .any(|suffix| name.ends_with(suffix))
        {
            inner = Some((i, name));
        }
    }
    if extras.base.is_some() {
        for expected in &names {
            if !extras.helpers.iter().any(|(found, _)| found == expected) {
                return Err(format!("{file}: {PACKAGE_METADATA} declares a complete Win7 package, but {expected} is missing"));
            }
        }
        if extras.helpers.len() != names.len() {
            return Err(format!("{file}: {PACKAGE_METADATA} has an unexpected companion executable"));
        }
        #[cfg(windows)]
        for (name, bytes) in &extras.helpers {
            if !bytes.starts_with(b"MZ") {
                return Err(format!("{file}: {name} is not a Windows executable"));
            }
        }
        return Ok(extras);
    }
    // Ordinary official ZIPs also contain helper executables; leave their
    // existing import behavior unchanged unless our explicit metadata is present.
    let Some((i, name)) = inner else {
        // Do not import helper executables from an ordinary official ZIP; only
        // the explicit Win7 metadata authorizes replacing the companion tools.
        return Ok(PackageExtras::default());
    };
    let entry = zip.by_index(i).map_err(|e| format!("{file}: {e}"))?;
    let archive = read_at_most(entry, file)?;
    if !name.ends_with(".zip") {
        return Ok(extras);
    }
    let inner = zip::ZipArchive::new(Cursor::new(archive))
        .map_err(|e| format!("{name}: {e}"))?;
    extras_from_zip(inner, file, false)
}

'''
replace_once(anchor, extras + anchor, "package reader insertion")

install_anchor = '''fn install_in(
    versions: &Path,
    base: &str,
    program: &[u8],
    file: &str,
    date: &str,
) -> Result<String, String> {
    let sha256: String = Sha256::digest(program)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
'''
install_new = '''fn install_in(
    versions: &Path,
    base: &str,
    program: &[u8],
    file: &str,
    date: &str,
) -> Result<String, String> {
    install_in_with_extras(versions, base, program, file, date, &PackageExtras::default())
}

fn install_in_with_extras(
    versions: &Path,
    base: &str,
    program: &[u8],
    file: &str,
    date: &str,
    extras: &PackageExtras,
) -> Result<String, String> {
    let sha256: String = if extras.base.is_none() && extras.helpers.is_empty() {
        Sha256::digest(program).iter().map(|b| format!("{b:02x}")).collect()
    } else {
        let mut hash = Sha256::new();
        hash.update(b"horizon imported package v1\\0");
        hash.update(program);
        if let Some(base) = &extras.base {
            hash.update(base.as_bytes());
        }
        let mut helpers = extras.helpers.clone();
        helpers.sort_by(|a, b| a.0.cmp(&b.0));
        for (name, bytes) in helpers {
            hash.update(name.as_bytes());
            hash.update((bytes.len() as u64).to_le_bytes());
            hash.update(bytes);
        }
        hash.finalize().iter().map(|b| format!("{b:02x}")).collect()
    };
'''
replace_once(install_anchor, install_new, "install routine")

replace_once(
'''        .and_then(|()| finish(&partial, &dir, program, &record).map_err(|e| e.to_string()));''',
'''        .and_then(|()| finish(&partial, &dir, program, &record, extras).map_err(|e| e.to_string()));''',
"install finish call",
)

replace_once(
'''    record: &serde_json::Value,
) -> std::io::Result<()> {
    fs::write(partial.join(CLIENT), program)?;
''',
'''    record: &serde_json::Value,
    extras: &PackageExtras,
) -> std::io::Result<()> {
    fs::write(partial.join(CLIENT), program)?;
    let allowed = companion_names();
    for (name, bytes) in &extras.helpers {
        if !allowed.iter().any(|expected| expected == name) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                format!("unsupported companion executable: {name}"),
            ));
        }
        let path = partial.join(name);
        if let Ok(metadata) = fs::metadata(&path) {
            let mut permissions = metadata.permissions();
            permissions.set_readonly(false);
            fs::set_permissions(&path, permissions)?;
        }
        fs::write(path, bytes)?;
    }
''',
"write companion executables",
)

test_anchor = '''    #[test]
    fn the_base_is_the_selected_release_or_the_newest_one() {'''
test = r'''    #[test]
    fn a_windows_binary_archive_imports_its_helpers_and_declared_base() {
        use std::io::Write;
        let versions = dir("win7-package");
        let base_tag = "nightly-2026-11-03";
        let base = versions.join(base_tag);
        fs::create_dir_all(&base).unwrap();
        fs::write(base.join(".installed"), b"").unwrap();
        fs::write(base.join(CLIENT), b"official client").unwrap();
        let names = companion_names();
        for name in &names {
            fs::write(base.join(name), format!("official {name}")).unwrap();
        }

        let archive_path = versions.join("Horizon-Windows7-Game-Binaries.zip");
        let mut zip = zip::ZipWriter::new(fs::File::create(&archive_path).unwrap());
        let options = zip::write::SimpleFileOptions::default();
        zip.start_file(format!("bin/{CLIENT}"), options).unwrap();
        zip.write_all(&program(b"win7 game")).unwrap();
        let payloads: [&[u8]; 3] = [b"MZwin7 ctl", b"MZwin7 prepare", b"MZwin7 server"];
        for (name, body) in names.iter().zip(payloads) {
            zip.start_file(format!("bin/{name}"), options).unwrap();
            zip.write_all(body).unwrap();
        }
        zip.start_file(PACKAGE_METADATA, options).unwrap();
        zip.write_all(br#"{"schema":1,"base":"nightly-2026-11-03","source_commit":"294448014fba585f8d5d09dd8886f482493b6417","target":"x86_64-win7-windows-msvc"}"#).unwrap();
        zip.finish().unwrap();

        let extras = read_package_extras(&archive_path, "Horizon-Windows7-Game-Binaries.zip").unwrap();
        assert_eq!(extras.base.as_deref(), Some(base_tag));
        assert_eq!(extras.helpers.len(), 3);
        let client = read_program(&archive_path, "Horizon-Windows7-Game-Binaries.zip").unwrap();
        let tag = install_in_with_extras(
            &versions,
            base_tag,
            &client,
            "Horizon-Windows7-Game-Binaries.zip",
            "2026-11-04",
            &extras,
        ).unwrap();
        let installed = versions.join(&tag);
        assert_eq!(fs::read(installed.join(CLIENT)).unwrap(), client);
        assert_eq!(fs::read(base.join(CLIENT)).unwrap(), b"official client");
        let payloads: [&[u8]; 3] = [b"MZwin7 ctl", b"MZwin7 prepare", b"MZwin7 server"];
        for (name, body) in names.iter().zip(payloads) {
            assert_eq!(fs::read(installed.join(name)).unwrap(), body);
            assert!(String::from_utf8(fs::read(base.join(name)).unwrap()).unwrap().starts_with("official "));
        }
        let record: serde_json::Value =
            serde_json::from_slice(&fs::read(installed.join(RECORD)).unwrap()).unwrap();
        assert_eq!(record["base"], base_tag);
        assert!(installed.join(".installed").is_file());
        let _ = fs::remove_dir_all(versions);
    }

'''
replace_once(test_anchor, test + test_anchor, "package import test insertion")

source.write_text(text, encoding="utf-8", newline="\n")
print(f"Patched {source}")
