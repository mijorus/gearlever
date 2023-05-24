from gi.repository import Gtk

class AboutDialog(Gtk.AboutDialog):
    def __init__(self, parent, version):
        Gtk.AboutDialog.__init__(self)
        self.props.program_name = 'boutique'
        self.props.version = version
        self.props.authors = ['Lorenzo Paderi']
        self.props.copyright = '2022 Lorenzo Paderi'
        self.props.logo_icon_name = 'it.mijorus.boutique'
        self.props.modal = True
        self.set_transient_for(parent)