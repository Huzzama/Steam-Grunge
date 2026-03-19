%global debug_package %{nil}
%global _enable_debug_packages 0

Name:           steam-grunge-editor
Version:        %{APP_VERSION}
Release:        1%{?dist}
Summary:        A grunge-style editor for Steam artwork and assets

License:        MIT
URL:            https://github.com/Huzzama/Steam-Grunge

BuildArch:      x86_64
AutoReqProv:    no

Source0:        steam-grunge-editor-bin-%{version}.tar.gz
Source1:        steam-grunge-editor.desktop
Source2:        steam-grunge-editor.png

%description
Steam Grunge Editor is a PySide6-based graphical tool for creating and
syncing grunge-style custom artwork for your Steam library.

Supports cover, wide/header, hero, logo and icon artwork.
Includes SteamGridDB integration, layer FX, and direct Steam sync.
Distributed as a self-contained binary — no system Python required.

%prep
%autosetup -n steam-grunge-editor-bin-%{version}

%build

%install
install -Dm755 steam-grunge-editor \
    %{buildroot}%{_bindir}/steam-grunge-editor

install -Dm644 %{SOURCE1} \
    %{buildroot}%{_datadir}/applications/steam-grunge-editor.desktop

install -Dm644 %{SOURCE2} \
    %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/steam-grunge-editor.png

%files
%{_bindir}/steam-grunge-editor
%{_datadir}/applications/steam-grunge-editor.desktop
%{_datadir}/icons/hicolor/256x256/apps/steam-grunge-editor.png

%post
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%postun
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%changelog
* %(date "+%a %b %d %Y") Packager <build@steam-grunge-editor> - %{version}-1
- v2.1.0: Pro post-sync strategy system, Flatpak/Steam Deck support,
  smart batch sync, rotating file logger, game-running guard
