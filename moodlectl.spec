# PyInstaller spec for moodlectl
# Build: pyinstaller moodlectl.spec
# Output: dist/moodlectl/ (onedir — fast startup, fewer antivirus issues than onefile)
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

datas  = collect_data_files("matplotlib")   # fonts, styles, locale (~50 MB)
datas += collect_data_files("plotext")
datas += collect_data_files("selenium")

hiddenimports = [
    # python-dotenv
    "dotenv",
    # rich
    "rich.logging",
    "rich._windows",
    "rich._windows_renderer",
    # requests
    "charset_normalizer",
    "urllib3.contrib",
    # beautifulsoup4
    "bs4.builder._htmlparser",
    # selenium
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
    "selenium.webdriver.common.by",
    # webdriver-manager (downloads ChromeDriver at runtime to ~/.wdm/)
    "webdriver_manager.chrome",
    "webdriver_manager.core.driver_cache",
    "webdriver_manager.core.config",
    # matplotlib
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_pdf",
    # anthropic / httpx
    "httpx",
    "httpx._transports.default",
    "anyio",
    "anyio._backends._asyncio",
]

a = Analysis(
    ["moodlectl/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "_tkinter", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="moodlectl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon="assets/icon.ico",
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="moodlectl",
)
