# Gear Lever


<p align="center">
  <img width="150" src="data/icons/hicolor/scalable/apps/it.mijorus.gearlever.svg">
</p>

<p align="center"><a href="https://flatstat.mijorus.it/app/it.mijorus.gearlever"  align="center"><img width="150" src="https://img.shields.io/endpoint?url=https://flathub-stats-backend.vercel.app/badges/it.mijorus.gearlever/shields.io.json"></a></p>



## Features
- Integrate AppImages into your app menu with **just one click**
- **Drag and drop** files directly from your file manager
- Keep all the AppImages organized in a custom folder
- Open new AppImages directly with Gear lever
- **Manage updates**: keep older versions installed or replace them with the latest release
- Save CLI apps with their executable name automatically
- Modern and Fresh UI

## Download
<a href="https://flathub.org/apps/details/it.mijorus.gearlever" align="center">
  <img width="240" src="https://flathub.org/api/badge?svg&locale=en" alt="Get it on Flathub">
</a>

## CLI
Starting from version 3.0.0, Gear Lever includes some useful command line tools to manage your AppImages. The CLI uses the same logics as the UI.

Please use `flatpak run it.mijorus.gearlever --help` to get an updated version of this help screen

```sh
Usage: flatpak run it.mijorus.gearlever [OPTION...]
# OR gearlever [OPTION...] if using the alias

--integrate        Integrate an AppImage file                                                                 
--update           Update an AppImage file       
--update --all     Update all apps                                                           
--remove           Trashes an AppImage, its .desktop file and icons                                           
--list-installed   List integrated apps                                                                       
--list-updates     List available updates   
```

For an improved user experience, add the following line to your `.bashrc` file

```sh
alias gearlever='flatpak run it.mijorus.gearlever'
```

##  Support me
<a href="https://ko-fi.com/mijorus" align="center">
  <img width="250" src="https://mijorus.it/kofi-support.png">
</a>

___

Get the [bundle from github](https://github.com/mijorus/gearlever/releases) (no auto-updates)
```sh
# From your Downloads folder
flatpak install --bundle --user gearlever.flatpak
```

## Changelog
[Open changelog](https://gearlever.mijorus.it/changelog)

## Permissions

- `--talk-name=org.freedesktop.Flatpak`: This permission is required in order to open apps and refresh the system menu when a new app is installed; if the user disables this permission manually (eg. with Flatseal), Gear lever should continue to work normally, except you would not be able to open apps directly.

## Preview
<p align="center">
  <img width="850" src="https://raw.githubusercontent.com/mijorus/gearlever/master/docs/gearlever3.png">
</p>

## Building and running
- Option #1 (suggested)

  **Open this project with Gnome Builder and press RUN (the play icon on top)**

- Option #2
  ```sh
  # Run the app
  flatpak-builder build/ it.mijorus.gearlever.json --user --force-clean
  flatpak-builder --run build/ it.mijorus.gearlever.json gearlever

  # Install the app
  flatpak-builder build/ it.mijorus.gearlever.json --user --install --force-clean
  ```

## Run CLI tests
```sh
python3 -m unittest tests/test_cli.py
```
