# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file backend bundle; the frontend is packaged by Tauri."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent

datas = []
for directory in (
    "alembic",
    "configs",
    "dashboard/templates",
    "regression",
    "scripts",
    "tests",
):
    source = ROOT / directory
    if source.is_dir():
        datas.append((str(source), directory))

for filename in ("alembic.ini", "pytest.ini", "wifi_lab_reprovision_robust.sh"):
    source = ROOT / filename
    if source.is_file():
        datas.append((str(source), "."))

hiddenimports = []
for package in ("dashboard", "lib", "regression", "tests"):
    try:
        hiddenimports.extend(collect_submodules(package))
    except ImportError:
        pass

binaries = []
for package in (
    "alembic",
    "cryptography",
    "flask",
    "jinja2",
    "netmiko",
    "paramiko",
    "pytest",
    "scapy",
    "sqlalchemy",
    "yaml",
):
    try:
        package_datas, package_binaries, package_imports = collect_all(package)
    except ImportError:
        continue
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_imports)

a = Analysis(
    [str(ROOT / "scripts" / "netregress_desktop_backend.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "test"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="netregress-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
