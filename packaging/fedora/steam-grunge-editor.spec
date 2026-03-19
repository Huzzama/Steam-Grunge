# ─────────────────────────────────────────────────────────────────────────────
# steam-grunge-editor.spec
#
# RPM spec for Steam Grunge Editor — precompiled PyInstaller binary.
# No Python, pip, or compilation required on the build or target machine.
# ─────────────────────────────────────────────────────────────────────────────

# Suppress ALL debug subpackages (debug, debuginfo, debugsource).
# Required for PyInstaller binaries on Fedora 41+: the brp-python-bytecompile
# and add-determinism macros now generate a debugsource subpackage even when
# there are no sources to collect, causing:
#   "error: Empty %files file .../debugsourcefiles.list"
# Both directives are needed — %debug_package alone is not enough on fc41.
%global debug_package   %{nil}
%global _enable_debug_packages 0

# Also disable the dwz (DWARF compression) pass — not applicable to a
# PyInstaller single-file binary and can cause spurious build failures.
%global __os_install_post %(echo '%{__os_install_post}' | sed -e 's!/usr/lib[^[:space:]]*/brp-python-bytecompile[[:space:]].*$!!g')

Name:           steam-grunge-editor
Version:        %{getenv:APP_VERSION}
Release:        1%{?dist}
Summary:        A grunge-style editor for Steam artwork and assets

License:        MIT
URL:            https://github.com/Huzzama/Steam-Grunge

# Precompiled PyInstaller binary — x86_64 only, no compilation on target.
BuildArch:      x86_64

# PyInstaller bundles Qt / PySide6 — no system runtime deps needed.
AutoReqProv:    no

# ── Sources ───────────────────────────────────────────────────────────────────
Source0:        steam-grunge-editor-bin-%{version}.tar.gz
Source1:        steam-grunge-editor.desktop
Source2:        steam-grunge-editor.png

%description
Steam Grunge Editor is a PySide6-based graphical tool for creating and
syncing grunge-style custom artwork for your Steam library.

Supports cover, wide/header, hero, logo and icon artwork types.
Includes SteamGridDB integration, layer FX, and direct Steam sync.

Distributed as a self-contained binary — no system Python required.


# ── Prep ──────────────────────────────────────────────────────────────────────
%prep
%autosetup -n steam-grunge-editor-bin-%{version}


# ── Build ─────────────────────────────────────────────────────────────────────
%build
# Nothing to compile — binary is pre-built by PyInstaller in CI.


# ── Install ───────────────────────────────────────────────────────────────────
%install
# Binary → /usr/bin/
install -Dm755 steam-grunge-editor \
    %{buildroot}%{_bindir}/steam-grunge-editor

# Desktop entry → /usr/share/applications/
install -Dm644 %{SOURCE1} \
    %{buildroot}%{_datadir}/applications/steam-grunge-editor.desktop

# Icon → /usr/share/icons/hicolor/256x256/apps/
install -Dm644 %{SOURCE2} \
    %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/steam-grunge-editor.png


# ── Files ─────────────────────────────────────────────────────────────────────
%files
%{_bindir}/steam-grunge-editor
%{_datadir}/applications/steam-grunge-editor.desktop
%{_datadir}/icons/hicolor/256x256/apps/steam-grunge-editor.png


# ── Post-install / Post-uninstall scriptlets ──────────────────────────────────
%post
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%postun
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :


# ── Changelog ─────────────────────────────────────────────────────────────────
%changelog
* %(date "+%a %b %d %Y") Packager <build@steam-grunge-editor> - %{version}-1
- v2.1.0: Pro-level post-sync strategy system, Flatpak/Steam Deck support,
  smart batch sync, rotating file logger, game-running guard
