from pathlib import Path
import sys

backend_path = Path(sys.argv[1])
main_path = Path(sys.argv[2])
backend = backend_path.read_text(encoding="utf-8")
main = main_path.read_text(encoding="utf-8")

# Replace the exact function by its stable surrounding headings instead of matching
# every formatting detail. This is intentionally strict about the expected upstream version.
function = backend.find("pub fn switch_to_dx12(")
start = backend.rfind("/// Sets ", 0, function)
end = backend.find("\n/// The last", function)
if function < 0 or start < 0 or end < 0:
    raise SystemExit("Could not locate the upstream Vulkan crash fallback function")
new_function = r'''/// Sets \`graphicsApi:opengl\` in \`home\`'s graphics settings when unset, auto, or a
/// legacy DX12 preference. Windows 7 has no DirectX 12 runtime; OpenGL is the fallback.
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
                if value.trim() != "auto" && value.trim() != "dx12" {
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
    fs::write(&path, lines.join("\n") + "\n").map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(true)
}

'''
backend = backend[:start] + new_function + backend[end:]
backend = backend.replace("switch_to_dx12", "switch_to_opengl")
backend = backend.replace("a_renderer_start_crashes_switches_auto_to_dx12_once", "a_renderer_start_crash_switches_auto_to_opengl_once")
backend = backend.replace("a_renderer_start_crash_switches_auto_to_dx12_once", "a_renderer_start_crash_switches_auto_to_opengl_once")
backend = backend.replace("horizon-dx12-switch-", "horizon-opengl-switch-")
backend = backend.replace("graphicsApi:dx12", "graphicsApi:opengl")
backend = backend.replace(
    "// Already DirectX 12, or the player's own Vulkan: left alone.",
    "// Already OpenGL, or the player's own Vulkan: left alone.",
)
backend = backend.replace(
    "// Auto becomes DirectX 12 and the other settings stay.",
    "// Auto becomes OpenGL and the other settings stay.",
)

# Explicitly test that old profiles migrate from DX12 while Vulkan is preserved.
vulkan_test = r'''        fs::write(home.join(GRAPHICS_FILE), "sky:false\ngraphicsApi:vulkan\n").unwrap();
        assert_eq!(switch_to_opengl(&home), Ok(false));'''
migration_test = r'''        fs::write(home.join(GRAPHICS_FILE), "sky:false\ngraphicsApi:vulkan\n").unwrap();
        assert_eq!(switch_to_opengl(&home), Ok(false));
        // A saved DX12 choice is unavailable on Windows 7 and migrates to OpenGL.
        fs::write(home.join(GRAPHICS_FILE), "sky:false\ngraphicsApi:dx12\nfog:true\n").unwrap();
        assert_eq!(switch_to_opengl(&home), Ok(true));
        assert_eq!(
            fs::read_to_string(home.join(GRAPHICS_FILE)).unwrap(),
            "sky:false\ngraphicsApi:opengl\nfog:true\n"
        );'''
if backend.count(vulkan_test) != 1:
    raise SystemExit("Expected one explicit Vulkan assertion in the renderer fallback test")
backend = backend.replace(vulkan_test, migration_test, 1)

main_replacements = [
    ("switches the game to DirectX 12", "switches the game to OpenGL"),
    ("switched_to_dx12", "switched_to_opengl"),
    ("backend::switch_to_dx12", "backend::switch_to_opengl"),
    ("could not switch to DirectX 12", "could not switch to OpenGL"),
    ("the game now uses DirectX 12", "the game now uses OpenGL"),
]
for old, new in main_replacements:
    if old not in main:
        raise SystemExit(f"Expected launcher graphics fallback text not found: {old}")
    main = main.replace(old, new)

backend_path.write_text(backend, encoding="utf-8", newline="\n")
main_path.write_text(main, encoding="utf-8", newline="\n")
print("Win7 renderer crash recovery now migrates auto and legacy DX12 settings to OpenGL.")
