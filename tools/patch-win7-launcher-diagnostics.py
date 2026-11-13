#!/usr/bin/env python3
"""Add file-based startup diagnostics to the unchanged Horizon launcher UI."""

from pathlib import Path
import sys

MARKER = "// HORIZON_WIN7_STARTUP_DIAGNOSTICS"

HELPERS = r'''
// HORIZON_WIN7_STARTUP_DIAGNOSTICS
// This writes only a diagnostic file; it does not add a console or change the UI.
fn win7_startup_log(message: &str) {
    use std::io::Write as _;
    let mut candidates = Vec::new();
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        candidates.push(
            std::path::PathBuf::from(local)
                .join("Horizon Launcher")
                .join("startup-diagnostic.log"),
        );
    }
    if let Some(temp) = std::env::var_os("TEMP") {
        candidates.push(
            std::path::PathBuf::from(temp).join("HorizonLauncher-startup-diagnostic.log"),
        );
    }
    for path in candidates {
        if let Some(parent) = path.parent() {
            if std::fs::create_dir_all(parent).is_err() {
                continue;
            }
        }
        let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(&path)
        else {
            continue;
        };
        let elapsed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or_default();
        if writeln!(file, "[unix={elapsed}] {message}").is_ok() {
            break;
        }
    }
}

fn install_win7_startup_panic_hook() {
    std::panic::set_hook(Box::new(|info| {
        win7_startup_log(&format!("PANIC: {info}"));
    }));
}
'''

def patch(source: str) -> str:
    if MARKER in source:
        return source

    anchors = [
        ("fn main() {\n", HELPERS + "\nfn main() {\n"),
        (
            "fn main() {\n    if let Err(error) = console::attach_for_cli() {",
            'fn main() {\n    install_win7_startup_panic_hook();\n'
            '    win7_startup_log("main entered");\n'
            '    if let Err(error) = console::attach_for_cli() {',
        ),
        (
            "    gpui_platform::application()\n",
            '    win7_startup_log("before GPUI application initialization");\n'
            "    gpui_platform::application()\n",
        ),
        (
            "        .run(|cx: &mut App| {\n",
            '        .run(|cx: &mut App| {\n'
            '            win7_startup_log("GPUI run callback entered");\n',
        ),
        (
            "            cx.text_system()\n                .add_fonts",
            '            win7_startup_log("loading bundled fonts");\n'
            "            cx.text_system()\n                .add_fonts",
        ),
        (
            "            cx.open_window(\n",
            '            win7_startup_log("opening launcher window");\n'
            "            cx.open_window(\n",
        ),
        (
            '            .expect("window");\n',
            '            .expect("window");\n'
            '            win7_startup_log("launcher window created");\n',
        ),
    ]

    # Insert the helper block first, then apply all main() instrumentation.
    if source.count("fn main() {\n") != 1:
        raise SystemExit("Expected exactly one main() function in the pinned Horizon source")
    result = source.replace("fn main() {\n", HELPERS + "\nfn main() {\n", 1)

    for old, new in anchors[1:]:
        if result.count(old) != 1:
            raise SystemExit(f"Expected exactly one instrumentation anchor: {old[:90]!r}")
        result = result.replace(old, new, 1)

    required = [
        "install_win7_startup_panic_hook();",
        "before GPUI application initialization",
        "GPUI run callback entered",
        "loading bundled fonts",
        "opening launcher window",
        "launcher window created",
    ]
    if not all(item in result for item in required):
        raise SystemExit("Startup diagnostic self-check failed")
    return result


def self_test() -> None:
    sample = """fn main() {
    if let Err(error) = console::attach_for_cli() {
        eprintln!("{error}");
    }
    gpui_platform::application()
        .run(|cx: &mut App| {
            cx.text_system()
                .add_fonts(vec![])
                .expect("bundled fonts");
            cx.open_window(
                WindowOptions::default(),
                |window, cx| cx.new(|cx| Launcher::new(window, cx)),
            )
            .expect("window");
        });
}
"""
    first = patch(sample)
    second = patch(first)
    if first != second:
        raise SystemExit("Patch is not idempotent")
    if first.count(MARKER) != 1:
        raise SystemExit("Diagnostic helper marker is missing or duplicated")
    print("Startup diagnostic patch self-test passed (anchors, stages, panic hook, idempotency).")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif len(sys.argv) == 2:
        path = Path(sys.argv[1])
        original = path.read_text(encoding="utf-8")
        updated = patch(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
        print("Windows 7 launcher startup diagnostics installed.")
    else:
        raise SystemExit("Usage: patch-win7-launcher-diagnostics.py <launcher/src/main.rs> | --self-test")
