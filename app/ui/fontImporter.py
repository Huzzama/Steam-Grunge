"""
fontImporter.py  —  Font Import System for Steam Grunge Editor

Handles:
  • ZIP font pack import  (recursive scan inside ZIPs)
  • Individual .ttf / .otf file import
  • Duplicate detection (skip + log)
  • QFontDatabase registration of newly installed fonts
  • Returns summary for UI feedback

Public API
──────────
    result = import_fonts(paths: list[str], fonts_dir: str) -> ImportResult
    register_all_fonts(fonts_dir: str) -> int          # returns count registered

Called by EditorPanel after the user selects files via QFileDialog.
"""
from __future__ import annotations

import os
import shutil
import zipfile
import tempfile
import logging
from dataclasses import dataclass, field
from typing import List

log = logging.getLogger(__name__)

VALID_EXTS = {".ttf", ".otf", ".woff", ".woff2"}
# QFontDatabase only reliably supports TTF/OTF on all platforms
REGISTERABLE_EXTS = {".ttf", ".otf"}


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ImportResult:
    installed:   List[str] = field(default_factory=list)   # font filenames installed
    skipped:     List[str] = field(default_factory=list)   # duplicates skipped
    failed:      List[str] = field(default_factory=list)   # errors
    registered:  int = 0                                   # Qt font IDs registered

    @property
    def total(self) -> int:
        return len(self.installed) + len(self.skipped) + len(self.failed)

    def summary(self) -> str:
        parts = []
        if self.installed:
            parts.append(f"{len(self.installed)} font(s) installed")
        if self.skipped:
            parts.append(f"{len(self.skipped)} already existed")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if not parts:
            return "No valid fonts found."
        return " · ".join(parts) + "."


# ─────────────────────────────────────────────────────────────────────────────

def import_fonts(paths: List[str], fonts_dir: str) -> ImportResult:
    """
    Main entry point.
    paths     — list of file paths selected by the user (.zip, .ttf, .otf …)
    fonts_dir — destination directory (FONTS_DIR from config)
    """
    os.makedirs(fonts_dir, exist_ok=True)
    result = ImportResult()

    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".zip":
            _import_zip(path, fonts_dir, result)
        elif ext in VALID_EXTS:
            _install_font_file(path, fonts_dir, result)
        else:
            log.warning("Unsupported file type skipped: %s", path)
            result.failed.append(os.path.basename(path))

    # Register all newly installed fonts with Qt
    result.registered = _register_fonts(
        [os.path.join(fonts_dir, f) for f in result.installed]
    )
    return result


def register_all_fonts(fonts_dir: str) -> int:
    """
    Register every font in fonts_dir with QFontDatabase.
    Called once at startup so existing fonts are available immediately.
    Returns the number of font families successfully registered.
    """
    if not os.path.isdir(fonts_dir):
        return 0
    paths = [
        os.path.join(fonts_dir, f)
        for f in os.listdir(fonts_dir)
        if os.path.splitext(f)[1].lower() in REGISTERABLE_EXTS
    ]
    return _register_fonts(paths)


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────

def _import_zip(zip_path: str, fonts_dir: str, result: ImportResult):
    """Extract ZIP to a temp dir, scan recursively, install valid fonts."""
    if not zipfile.is_zipfile(zip_path):
        log.error("Not a valid ZIP file: %s", zip_path)
        result.failed.append(os.path.basename(zip_path))
        return

    with tempfile.TemporaryDirectory(prefix="sge_fonts_") as tmp:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp)
        except Exception as e:
            log.error("Failed to extract %s: %s", zip_path, e)
            result.failed.append(os.path.basename(zip_path))
            return

        # Recursively find all font files inside the extracted tree
        found_any = False
        for root, _, files in os.walk(tmp):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in VALID_EXTS:
                    full_path = os.path.join(root, fname)
                    _install_font_file(full_path, fonts_dir, result)
                    found_any = True

        if not found_any:
            log.warning("No valid fonts found in ZIP: %s", zip_path)
            # Don't add to failed — it's a user-level warning, not an error


def _install_font_file(src_path: str, fonts_dir: str, result: ImportResult):
    """Copy a single font file into fonts_dir, handling duplicates."""
    fname = os.path.basename(src_path)
    dest  = os.path.join(fonts_dir, fname)

    if os.path.exists(dest):
        log.info("Font already installed: %s", fname)
        result.skipped.append(fname)
        return

    try:
        shutil.copy2(src_path, dest)
        log.info("Installed font: %s", fname)
        result.installed.append(fname)
    except Exception as e:
        log.error("Failed to install %s: %s", fname, e)
        result.failed.append(fname)


def _register_fonts(paths: List[str]) -> int:
    """Register a list of font file paths with Qt's QFontDatabase."""
    try:
        from PySide6.QtGui import QFontDatabase
    except ImportError:
        return 0

    count = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        if os.path.splitext(path)[1].lower() not in REGISTERABLE_EXTS:
            continue
        try:
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                families = QFontDatabase.applicationFontFamilies(fid)
                log.debug("Registered font families: %s", families)
                count += len(families)
            else:
                log.warning("Qt rejected font: %s", path)
        except Exception as e:
            log.error("Error registering font %s: %s", path, e)

    return count