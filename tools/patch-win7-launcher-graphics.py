from pathlib import Path
import sys

backend_path = Path(sys.argv[1])
main_path = Path(sys.argv[2])
backend = backend_path.read_text(encoding="utf-8")
main = main_path.read_text(encoding="utf-8")

def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source match, found {count}")
    return source.replace(old, new, 1)

old_fn = '''/// Sets `graphicsApi:dx12` in `home`'s graphics settings when it is unset or `auto`, keeping
/// every other line. True when it changed; a player's own `vulkan` or `dx12` stays.
pub fn switch_to_dx12(home: &Path) -> Result<bool, String> {
    let path = home.join(GRAPHICS_FILE);
    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(e) => return Err(format!("{}: {e}", path.display())),
    };
    let mut lines: Vec<String> = Vec::new();
    let mut found = false;
    for line in text.lines() {
        match line.split_once(':') {
            Some((key, value)) if key.trim() == "graphicsApi" => {
                if value.trim() != "auto" && value.trim() != "dx12" {
                    return Ok(false);
                }
                found = true;
                lines.push("graphicsApi:dx12".to_owned());
            }
            _ => lines.push(line.to_owned()),
        }
    }
    if !found {
        lines.push("graphicsApi:dx12".to_owned());
    }
    fs::create_dir_all(home).map_err(|e| format!("{}: {e}", home.display()))?;
    fs::write(&path, lines.join("\\n") + "\\n").map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(true)
}'''

new_fn = '''/// Sets `graphicsApi:opengl` in `home`'s graphics settings when it is unset or `auto`.
/// Windows 7 has no DirectX 12 runtime; OpenGL is the fallback after a Vulkan driver crash.
pub fn switch_to_opengl(home: &Path) -> Result<bool, String> {
    let path = home.join(GRAPHICS_FILE);
    let text = match fs::read_to_string(&path) {
        Ok(text) => text,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(e) => return Err(format!("{}: {e}", path.display())),
    };
    let mut lines: Vec<String> = Vec::new();
    let mut found = false;
    for line in text.lines() {
        match line.split_once(':') {
            Some((key, value)) if key.trim() == "graphicsApi" => {
                if value.trim() != "auto" {
                    return Ok(false);
                }
                found = true;
                lines.push("graphicsApi:opengl".to_owned());
            }
            _ => lines.push(line.to_owned()),
        }
    }
    if !found {
        lines.push("graphicsApi:opengl".to_owned());
    }
    fs::create_dir_all(home).map_err(|e| format!("{}: {e}", home.display()))?;
    fs::write(&path, lines.join("\\n") + "\\n").map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(true)
}'''
backend = replace_once(backend, old_fn, new_fn, "Windows 7 graphics fallback function")
backend = replace_once(
    backend,
    "fn a_renderer_start_crash_switches_auto_to_dx12_once()",
    "fn a_renderer_start_crash_switches_auto_to_opengl_once()",
    "fallback test name",
)
backend = replace_once(
    backend,
    "horizon-dx12-switch-",
    "horizon-opengl-switch-",
    "fallback test temp directory",
)
backend = backend.replace("switch_to_dx12(", "switch_to_opengl(")
backend = backend.replace("graphicsApi:dx12", "graphicsApi:opengl")
backend = backend.replace(
    "// Already DirectX 12, or the player's own Vulkan: left alone.",
    "// Already OpenGL, or the player's own Vulkan: left alone.",
)
backend = backend.replace(
    '''        fs::write(home.join(GRAPHICS_FILE), "sky:false\ngraphicsApi:vulkan\n").unwrap();
        assert_eq!(switch_to_opengl(&home), Ok(false));''',
    '''        fs::write(home.join(GRAPHICS_FILE), "sky:false\ngraphicsApi:vulkan\n").unwrap();
        assert_eq!(switch_to_opengl(&home), Ok(false));
        // A legacy DX12 preference is unsupported on Windows 7 and migrates to OpenGL.
        fs::write(home.join(GRAPHICS_FILE), "sky:false\ngraphicsApi:dx12\nfog:true\n").unwrap();
        assert_eq!(switch_to_opengl(&home), Ok(true));
        assert_eq!(
            fs::read_to_string(home.join(GRAPHICS_FILE)).unwrap(),
            "sky:false\ngraphicsApi:opengl\nfog:true\n"
        );''',
    1,
)
backend = backend.replace(
    "// Auto becomes DirectX 12 and the other settings stay.",
    "// Auto becomes OpenGL and the other settings stay.",
)

main = replace_once(
    main,
    "switches the game to DirectX 12",
    "switches the game to OpenGL",
    "fallback description",
)
main = main.replace("switched_to_dx12", "switched_to_opengl")
main = main.replace("backend::switch_to_dx12", "backend::switch_to_opengl")
main = replace_once(
    main,
    "could not switch to DirectX 12",
    "could not switch to OpenGL",
    "fallback error text",
)

backend_path.write_text(backend, encoding="utf-8", newline="\n")
main_path.write_text(main, encoding="utf-8", newline="\n")
print("Updated the Win7 launcher recovery path from DirectX 12 to OpenGL.")
