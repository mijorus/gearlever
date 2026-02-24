project('gearlever',
          version: '4.4.6',
    meson_version: '>= 0.59.0',
  default_options: [ 'warning_level=2',
                   ],
)

i18n = import('i18n')

gnome = import('gnome')



subdir('data')
subdir('src')
subdir('po')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)

meson.add_install_script('build-aux/meson/postinstall.py')
