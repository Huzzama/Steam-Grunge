# Steam Grunge Editor — RPM spec. Built by packaging/fedora/build-rpm.sh,
# which passes APP_VERSION and a tarball with the self-contained PyInstaller
# folder (bundle/), the .desktop file and the icon.
%global debug_package %{nil}
%global __strip /bin/true
%global __brp_check_rpaths %{nil}
%global _build_id_links none

Name:           steam-grunge-editor
Version:        %{APP_VERSION}
Release:        1%{?dist}
Summary:        Grunge-style artwork editor for your Steam library
License:        MIT
URL:            https://github.com/Huzzama/Steam-Grunge
BuildArch:      x86_64
# The bundle carries its own Python and Qt; only the usual desktop libraries
# are needed from the system.
AutoReqProv:    no
Requires:       mesa-libGL mesa-libEGL fontconfig libxkbcommon libxkbcommon-x11 dbus-libs xcb-util-cursor xcb-util-wm xcb-util-keysyms xcb-util-renderutil
Source0:        steam-grunge-editor-bin-%{version}.tar.gz

%description
Create distressed, grunge-style custom artwork for your Steam library:
search SteamGridDB, add layers, film grain and VHS effects, and apply
covers, heroes, logos and icons straight to Steam.

%prep
%autosetup -n steam-grunge-editor-bin-%{version}

%build

%install
mkdir -p %{buildroot}%{_prefix}/lib/%{name} %{buildroot}%{_bindir}
cp -a bundle/. %{buildroot}%{_prefix}/lib/%{name}/
ln -s %{_prefix}/lib/%{name}/%{name} %{buildroot}%{_bindir}/%{name}
install -Dm644 %{name}.desktop %{buildroot}%{_datadir}/applications/%{name}.desktop
install -Dm644 %{name}.png %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/%{name}.png

%files
%{_prefix}/lib/%{name}/
%{_bindir}/%{name}
%{_datadir}/applications/%{name}.desktop
%{_datadir}/icons/hicolor/256x256/apps/%{name}.png

%post
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :

%postun
/usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
/usr/bin/update-desktop-database -q %{_datadir}/applications &>/dev/null || :
