# Boutique

This project is no longer in development 😢, sorry for that...

___

<p align="center">
  <img width="150" src="data/icons/hicolor/scalable/apps/it.mijorus.boutique.svg">
</p>

<p align="center">
  <img width="500" src="https://user-images.githubusercontent.com/39067225/180618676-15405cd2-dde9-4b13-970c-dd30958d5c12.png">
</p>

<p align="center">
  <img width="500" src="https://user-images.githubusercontent.com/39067225/180618679-4d0fe0b6-9264-445e-8d3c-73bc09928e73.png">
</p>


A work-in-progress Flatpak and Appimages app manager.

Made with GTK4

## Credits

Icon by daudix-ufo
https://daudix-ufo.github.io/works/icons/

Thanks!

## Testing

(please keep in mind this is alpha software)
 
 1. Clone the repo
 2. move into the cloned repo
 3. run these commands:

```sh
# builds the project 
flatpak-builder build/ it.mijorus.boutique.json --user --force-clean

# runs the project
flatpak-builder --run build/ it.mijorus.boutique.json boutique
```
