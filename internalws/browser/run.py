from workspace import BrowserWorkspace

def register(kernel):
    """Регистрация встроенного браузерного воркспейса в микроядре."""
    ws = BrowserWorkspace(runtime_id="browser", bus=kernel._bus)
    kernel._manifest_registry["browser"] = {
        "manifest": ws.manifest,
        "capabilities": ["dom.interact", "browser.control"],
        "behaviors": [],
        "features": ws.manifest.features
    }
    return ws

def install(ctx):
    print("Installing Built-in Browser Workspace...")

def start(ctx):
    print("Starting Built-in Browser Workspace...")

def stop(ctx):
    print("Stopping Built-in Browser Workspace...")

def uninstall(ctx):
    print("Uninstalling Built-in Browser Workspace...")
