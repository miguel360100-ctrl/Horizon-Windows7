from pathlib import Path
import sys
import tempfile

WAKE_OLD = '''        let mut notification = self.suspend_resume_notification.borrow_mut();
        if notification.is_none() {
            *notification = unsafe {
                // SAFETY: self.handle is the platform window receiving WM_POWERBROADCAST.
                RegisterSuspendResumeNotification(
                    HANDLE(self.handle.0),
                    DEVICE_NOTIFY_WINDOW_HANDLE,
                )
                .log_err()
            };
        }
'''
WAKE_NEW = '''        // RegisterSuspendResumeNotification was introduced in Windows 8.
        // Keep the callback API available, but do not import or call this API on Windows 7.
        #[cfg(not(feature = "windows7-compat"))]
        {
            let mut notification = self.suspend_resume_notification.borrow_mut();
            if notification.is_none() {
                *notification = unsafe {
                    // SAFETY: self.handle is the platform window receiving WM_POWERBROADCAST.
                    RegisterSuspendResumeNotification(
                        HANDLE(self.handle.0),
                        DEVICE_NOTIFY_WINDOW_HANDLE,
                    )
                    .log_err()
                };
            }
        }
'''
DROP_OLD = '''            if let Some(notification) = self.suspend_resume_notification.borrow_mut().take() {
                // SAFETY: notification was returned by RegisterSuspendResumeNotification.
                UnregisterSuspendResumeNotification(notification).log_err();
            }
'''
DROP_NEW = '''            // The Windows 8+ suspend/resume notification APIs are not used by Win7 builds.
            #[cfg(not(feature = "windows7-compat"))]
            if let Some(notification) = self.suspend_resume_notification.borrow_mut().take() {
                // SAFETY: notification was returned by RegisterSuspendResumeNotification.
                UnregisterSuspendResumeNotification(notification).log_err();
            }
'''

def patch(text: str) -> str:
    if WAKE_NEW in text and DROP_NEW in text:
        return text
    if text.count(WAKE_OLD) != 1:
        raise SystemExit(f"Expected one suspend/resume registration block, found {text.count(WAKE_OLD)}")
    if text.count(DROP_OLD) != 1:
        raise SystemExit(f"Expected one suspend/resume unregistration block, found {text.count(DROP_OLD)}")
    return text.replace(WAKE_OLD, WAKE_NEW, 1).replace(DROP_OLD, DROP_NEW, 1)

if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
    fixture = "prefix\n" + WAKE_OLD + "middle\n" + DROP_OLD + "suffix\n"
    result = patch(fixture)
    assert WAKE_NEW in result and DROP_NEW in result
    assert patch(result) == result
    assert "RegisterSuspendResumeNotification(" in result
    assert '#[cfg(not(feature = "windows7-compat"))]' in result
    print("Suspend/resume compatibility patch tests passed (including idempotence).")
    raise SystemExit(0)

if len(sys.argv) != 2:
    raise SystemExit("Usage: patch-win7-power-notifications.py <path-to-platform.rs>")

source = Path(sys.argv[1])
original = source.read_text(encoding="utf-8")
updated = patch(original)
if updated == original:
    print("Windows 7 power-notification compatibility patch is already applied.")
else:
    source.write_text(updated, encoding="utf-8", newline="\n")
    print("Disabled Windows 8-only suspend/resume notifications in Windows 7 builds.")
