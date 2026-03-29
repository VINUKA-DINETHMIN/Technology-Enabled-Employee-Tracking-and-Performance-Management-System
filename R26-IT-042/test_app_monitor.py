import time
import platform
import logging

# Minimal version of the logic in app_usage_monitor.py
def test_app_monitoring():
    os_name = platform.system()
    print(f"Testing App Monitoring on {os_name}...")
    
    for i in range(5):
        try:
            if os_name == "Windows":
                import ctypes
                import psutil
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                pid = ctypes.c_ulong(0)
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    proc = psutil.Process(pid.value)
                    app_name = proc.name().replace(".exe", "").strip() or "Unknown"
                    print(f"[{i+1}/5] Active App: {app_name} (PID: {pid.value})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    print(f"[{i+1}/5] Active App: [Access Denied / System Process]")
            else:
                print(f"[{i+1}/5] Testing only implemented for Windows in this script.")
        except Exception as e:
            print(f"[{i+1}/5] Error: {e}")
        time.sleep(1)

if __name__ == "__main__":
    test_app_monitoring()
