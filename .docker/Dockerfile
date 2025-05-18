# Dockerfile for building GearLever AppImage in a clean Ubuntu 24.04 environment
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libglib2.0-dev \
    meson \
    ninja-build \
    python3-gi \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-venv \
    python3-cairo \
    python3.12-dev \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    libglib2.0-bin \
    desktop-file-utils \
    squashfs-tools \
    p7zip-full \
    python3-pyxdg \
    libdbus-1-dev \
    wget \
    gettext \
    ca-certificates \
    libfuse2 \
    file \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Use more specific COPY instructions to avoid unnecessary rebuilds
COPY src/ /build/src/
COPY data/ /build/data/
COPY build-aux/ /build/build-aux/
COPY po/ /build/po/
COPY meson.build requirements.txt it.mijorus.gearlever.json /build/

# Ensure AppDir exists before creating AppRun
RUN mkdir -p AppDir && \
    echo '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexport PYTHONPATH="$HERE/usr/lib/python3.12/site-packages:$HERE/usr/lib/python3.12/dist-packages:$PYTHONPATH"\nexport XDG_DATA_DIRS="$HERE/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"\nexport GSETTINGS_SCHEMA_DIR="${APPDIR}/usr/share/glib-2.0/schemas"\nexec "$HERE/usr/bin/gearlever" "$@"' > AppDir/AppRun && \
    chmod +x AppDir/AppRun

# Install Python dependencies directly into AppDir
RUN pip3 install --prefix=$PWD/AppDir --break-system-packages -r requirements.txt

ENV PATH="/build/AppDir/usr/bin:$PATH"

RUN meson setup builddir --prefix=/usr && \
    ninja -C builddir && \
    DESTDIR=$PWD/AppDir ninja -C builddir install

# Ensure GSettings schema is compiled and included in AppDir
RUN glib-compile-schemas data/ && \
    mkdir -p AppDir/usr/share/glib-2.0/schemas && \
    cp data/gschemas.compiled AppDir/usr/share/glib-2.0/schemas/

RUN mkdir -p AppDir/usr/share/glib-2.0/schemas
RUN cp data/gschemas.compiled AppDir/usr/share/glib-2.0/schemas/

RUN wget -O appimagetool https://github.com/AppImage/AppImageKit/releases/latest/download/appimagetool-x86_64.AppImage && \
    chmod +x appimagetool

RUN find AppDir
RUN cp AppDir/usr/share/applications/*.desktop AppDir/ || true
RUN cp AppDir/usr/share/icons/hicolor/scalable/apps/it.mijorus.gearlever.svg AppDir/ 2>/dev/null || true
RUN cp AppDir/usr/share/icons/hicolor/scalable/apps/it.mijorus.gearlever.png AppDir/ 2>/dev/null || true
RUN cp AppDir/usr/share/icons/hicolor/256x256/apps/it.mijorus.gearlever.png AppDir/ 2>/dev/null || true
RUN cp AppDir/usr/share/icons/hicolor/256x256/apps/it.mijorus.gearlever.svg AppDir/ 2>/dev/null || true
RUN APPIMAGE_EXTRACT_AND_RUN=1 ./appimagetool AppDir GearLever-x86_64.AppImage

VOLUME /output
# Set the default command to ensure the container exits after producing the artifact
CMD ["/bin/bash", "-c", "cp GearLever-x86_64.AppImage /output/"]
