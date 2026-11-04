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

gfx_path = root / "crates/horizon-client-render/src/gfx.rs"
gfx = gfx_path.read_text(encoding="utf-8")
old_instance = """    let dx12 = cfg!(windows) && descriptor.backends.contains(wgpu::Backends::DX12);
    // FXC spends about 2.6 s on every start compiling the pipelines (DXC about
    // 1 s); what it compiled once is kept in the game folder and read back
    // after that (third_party/wgpu-hal/src/dx12/disk_cache.rs).
    #[cfg(windows)]
    if dx12 {
        wgpu::hal::dx12::disk_cache::set_file(dx12_shader_cache(&crate::logging::game_home()));
    }
    if !cfg!(debug_assertions) && !dx12 {
        descriptor
            .flags
            .remove(wgpu::InstanceFlags::VALIDATION_INDIRECT_CALL);
    }"""
new_instance = """    // The Windows 7 build does not compile WGPU's DirectX 12 backend.
    if !cfg!(debug_assertions) {
        descriptor
            .flags
            .remove(wgpu::InstanceFlags::VALIDATION_INDIRECT_CALL);
    }"""
if gfx.count(old_instance) != 1:
    raise SystemExit("Win7 WGPU instance initialization: expected one DX12 block")
gfx = gfx.replace(old_instance, new_instance, 1)

old_order = """        GraphicsApi::Auto if windows => vec![Backends::VULKAN, Backends::DX12, Backends::GL],
        GraphicsApi::Auto => vec![Backends::VULKAN, Backends::GL],
        GraphicsApi::Dx12 if windows => vec![Backends::DX12],
        GraphicsApi::Vulkan | GraphicsApi::Dx12 => vec![Backends::VULKAN],"""
new_order = """        GraphicsApi::Auto if windows => vec![Backends::VULKAN, Backends::GL],
        GraphicsApi::Auto => vec![Backends::VULKAN, Backends::GL],
        // An old DX12 preference from an existing profile falls back to OpenGL
        // in the Windows 7 build rather than requesting an unavailable backend.
        GraphicsApi::Dx12 if windows => vec![Backends::GL],
        GraphicsApi::Vulkan | GraphicsApi::Dx12 => vec![Backends::VULKAN],"""
if gfx.count(old_order) != 1:
    raise SystemExit("Win7 backend order: expected one DX12 selection block")
gfx = gfx.replace(old_order, new_order, 1)

old_doc = """/// device. api is the player's choice (GraphicsApi::with_env applied);
/// os is std::env::consts::OS; wgpu_backend: whether WGPU_BACKEND is set,
/// which picks the backends itself. Auto tries Vulkan, then DirectX 12 on Windows,
/// then OpenGL (Windows and Linux) for GPUs with neither driver, each when the one
/// before has no surface, adapter or device. A native crash in the driver can't be
/// caught in the game; the launcher switches the setting to DirectX 12 after one"""
new_doc = """/// device. api is the player's choice (GraphicsApi::with_env applied);
/// os is std::env::consts::OS; wgpu_backend: whether WGPU_BACKEND is set,
/// which picks the backends itself. The Windows 7 build tries Vulkan, then OpenGL;
/// other platforms retain their own backend order. A native crash in the driver
/// can't be caught in the game; the launcher switches the setting to OpenGL after one"""
if gfx.count(old_doc) != 1:
    raise SystemExit("Win7 backend documentation: expected one DX12 passage")
gfx = gfx.replace(old_doc, new_doc, 1)
gfx_path.write_text(gfx, encoding="utf-8", newline="\n")

graphics_path.write_text(text, encoding="utf-8", newline="\n")
print("Disabled WGPU DX12 and removed DirectX 12 from the Windows 7 graphics choices.")
