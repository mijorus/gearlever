# Gear lever - manage AppImages

This project is in development...

___

<p align="center">
  <img width="150" src="data/icons/hicolor/scalable/apps/it.mijorus.gearlever.svg">
</p>

## Building and running

⚠️  This project is still potentially unstable, please report any bugs
```
# to run the app:
flatpak-builder build/ it.mijorus.gearlever.Devel.json --user --force-clean
flatpak-builder --run build/ it.mijorus.gearlever.Devel.json gearlever

# to install the app
flatpak-builder build/ it.mijorus.gearlever.Devel.json --user --install --force-clean
```
