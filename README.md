# Gear lever


<p align="center">
  <img width="150" src="data/icons/hicolor/scalable/apps/it.mijorus.gearlever.svg">
</p>

## Features
- Integrate AppImages into your app menu with **just click**
- **Drag and drop** files directly from your file manager
- Keep all the AppImages organized in a custom folder
- Open new AppImages directly with Gear lever
- **Manage updates**: keep older versions installed or replace them with the latest release
- Save CLI apps directly with their executable name
- Modern and Fresh UI

## Download
<a href="https://flathub.org/apps/details/it.mijorus.gearlever" align="center">
  <img width="200" src="https://flathub.org/assets/badges/flathub-badge-i-en.png">
</a>

___

Get the [bundle from github](https://github.com/mijorus/gearlever/releases) (no auto-updates)
```sh
# From your Downloads folder
flatpak install --bundle --user gearlever.flatpak
```

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
  flatpak-builder build/ it.mijorus.gearlever.Devel.json --user --force-clean
  flatpak-builder --run build/ it.mijorus.gearlever.Devel.json gearlever

  # Install the app
  flatpak-builder build/ it.mijorus.gearlever.Devel.json --user --install --force-clean
  ```
