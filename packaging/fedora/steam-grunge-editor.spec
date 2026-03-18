# ─────────────────────────────────────────────────────────────────────────────
# steam-grunge-editor.spec
#
# RPM spec for Steam Grunge Editor — precompiled PyInstaller binary.
# No Python, pip, or compilation required on the build or target machine.
# ─────────────────────────────────────────────────────────────────────────────

# Disable debug/debugsource packages — PyInstaller binary has no build-time
# debug info. Without this rpmbuild fails: "Empty %files debugsourcefiles.list"
%global debug_package %{nil}

Name:           steam-grunge-editor
Version:        %{getenv:APP_VERSION}
Release:        1%{?dist}
Summary:        A grunge-style editor for Steam artwork and assets

License:        MIT
URL:            https://github.com/youruser/steam-grunge-editor

# This package installs a precompiled binary — no build steps needed.
BuildArch:      x86_64

# ── No runtime dependencies ───────────────────────────────────────────────────
# The PyInstaller binary is fully self-contained.
# Qt / PySide6 libraries are bundled inside the binary itself.
AutoReqProv:    no

# ── Sources ───────────────────────────────────────────────────────────────────
# Source0: the PyInstaller binary (placed in SOURCES/ as a tarball)
# Source1: desktop entry
# Source2: application icon
Source0:        steam-grunge-editor-bin-%{version}.tar.gz
Source1:        steam-grunge-editor.desktop
Source2:        steam-grunge-editor.png

%description
Steam Grunge Editor is a PySide6-based graphical tool for editing and
applying grunge-style effects to Steam artwork and game assets.

Distributed as a self-contained binary — no system Python required.


# ── Prep ──────────────────────────────────────────────────────────────────────
%prep
# Extract the tarball containing the PyInstaller binary.
# Expected layout inside the tarball:
#   steam-grunge-editor-bin-%{version}/steam-grunge-editor
%autosetup -n steam-grunge-editor-bin-%{version}


# ── Build ─────────────────────────────────────────────────────────────────────
%build
# Nothing to compile — binary is already built by PyInstaller.


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
# Refresh the icon cache so the app appears in the system menu immediately.
%post
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%postun
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :


# ── Changelog ─────────────────────────────────────────────────────────────────
%changelog
* %(date "+%a %b %d %Y") Packager <you@example.com> - %{version}-1
- Initial RPM release
