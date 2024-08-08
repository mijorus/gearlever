pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
moduledir = join_paths(pkgdatadir, 'gearlever')
src_subdirs = [
  'assets',
  'components',
  'gtk',
  'lib',
  'models',
  'providers'
]
src_data = [
  'AppDetails.py',
  'BackgroudUpdatesFetcher.py',
  'GearleverWindow.py',
  'InstalledAppsList.py',
  'MultiInstall.py',
  'State.py',
  'WelcomeScreen.py',
  '__init__.py',
  'main.py',
  'preferences.py'
]

gnome = import('gnome')

gnome.compile_resources('gearlever',
  'gearlever.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)



python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', join_paths(get_option('prefix'), get_option('localedir')))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'gearlever.in',
  output: 'gearlever',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir')
)

foreach d: src_subdirs
  install_subdir(d, install_dir: moduledir)
endforeach

install_data(src_data, install_dir: moduledir)