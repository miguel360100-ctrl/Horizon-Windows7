from pathlib import Path
import sys

root = Path(sys.argv[1])

def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")

# WGPU's DX12 feature is unavailable on Windows 7. The game build keeps Vulkan and
# OpenGL (WGL) only; the ordinary upstream Windows build is not modified.
for relative in (
    "crates/horizon-client/Cargo.toml",
    "crates/horizon-client-lib/Cargo.toml",
    "crates/horizon-client-render/Cargo.toml",
):
    path = root / relative
    replace_once(
        path,
        'wgpu = { version = "30.0.1", default-features = false, features = ["dx12"] }',
        'wgpu = { version = "30.0.1", default-features = false }',
        f"disable WGPU DX12 backend in {relative}",
    )

graphics_path = root / "crates/horizon-client-render/src/graphics.rs"
text = graphics_path.read_text(encoding="utf-8")

def once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source match, found {count}")
    text = text.replace(old, new, 1)

once(
    "/// The graphics API the renderer runs on. Windows picks Vulkan, DirectX 12 or\n/// OpenGL; Linux picks Vulkan or OpenGL; macOS always uses its one backend\n/// (Metal). Applies at the next start.",
    "/// The graphics API the renderer runs on. Windows picks Vulkan or OpenGL;\n/// Linux picks Vulkan or OpenGL; macOS always uses its one backend (Metal).\n/// Applies at the next start.",
    "Windows 7 graphics API documentation",
)
once(
    "    /// Vulkan, then DirectX 12 (Windows), then OpenGL when neither has a surface, adapter or device.",
    "    /// Vulkan, then OpenGL when neither has a surface, adapter or device.",
    "Auto graphics API description",
)
once(
    """    pub const ALL: [GraphicsApi; 4] = [
        GraphicsApi::Auto,
        GraphicsApi::Vulkan,
        GraphicsApi::Dx12,
        GraphicsApi::OpenGl,
    ];""",
    """    pub const ALL: [GraphicsApi; 3] = [
        GraphicsApi::Auto,
        GraphicsApi::Vulkan,
        GraphicsApi::OpenGl,
    ];""",
    "supported graphics APIs",
)
once(
    """        const WINDOWS: [GraphicsApi; 4] = [
            GraphicsApi::Auto,
            GraphicsApi::Vulkan,
            GraphicsApi::Dx12,
            GraphicsApi::OpenGl,
        ];""",
    """        const WINDOWS: [GraphicsApi; 3] = [
            GraphicsApi::Auto,
            GraphicsApi::Vulkan,
            GraphicsApi::OpenGl,
        ];""",
    "Windows graphics choices",
)
once(
    "    /// HORIZON_GRAPHICS_API (auto, vulkan, dx12 or opengl) if set, else the setting.",
    "    /// HORIZON_GRAPHICS_API (auto, vulkan or opengl) if set, else the setting.",
    "graphics API environment documentation",
)
once(
    "    fn the_api_choice_matches_the_system() {\n        let choices = GraphicsApi::choices();",
    "    fn the_api_choice_matches_the_system() {\n        let choices = GraphicsApi::choices();\n        assert_eq!(GraphicsApi::from_name(\"dx12\"), None);",
    "Win7 graphics API test",
)
once(
    "            api: GraphicsApi::Dx12,",
    "            api: GraphicsApi::OpenGl,",
    "DX12 round-trip test fixture",
)
graphics_path.write_text(text, encoding="utf-8", newline="\n")
print("Disabled WGPU DX12 and removed DirectX 12 from the Windows 7 graphics choices.")
