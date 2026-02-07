from calibre.customize import StoreBase


class AnnasArchiveStore(StoreBase):
    """
    Wrapper class Calibre instantiates (no-arg ctor). We delegate runtime calls
    to the actual implementation in annas_archive.py.
    """
    name                = 'Anna\'s Archive'
    description         = 'The world\'s largest open-source open-data library.'
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'ScottBot10'
    version             = (0, 4, 8)
    minimum_calibre_version = (5, 0, 0)
    formats             = ['EPUB', 'MOBI', 'PDF', 'AZW3', 'CBR', 'CBZ', 'FB2']
    drm_free_only       = True

    # Calibre uses this to import the real implementation class
    actual_plugin = 'calibre_plugins.store_annas_archive.annas_archive:AnnasArchiveStore'

    def __init__(self, *args, **kwargs):
        # StoreBase expects a no-arg constructor; do not call the impl here.
        super().__init__(*args, **kwargs)

    def _impl(self, gui):
        # Load (or reuse) the real plugin instance bound to this gui.
        try:
            if getattr(self, 'actual_plugin_object', None) is None or getattr(self.actual_plugin_object, 'gui', None) is not gui:
                self.actual_plugin_object = self.load_actual_plugin(gui)
        except Exception:
            # Fallback: force reload
            self.actual_plugin_object = self.load_actual_plugin(gui)
        return self.actual_plugin_object

    def open(self, gui, parent=None, detail_item=None, external=False):
        return self._impl(gui).open(gui=gui, parent=parent, detail_item=detail_item, external=external)

    def search(self, query, max_results=10, timeout=60):
        return self._impl(getattr(self, 'gui', None)).search(query, max_results=max_results, timeout=timeout)

    def get_details(self, search_result, timeout=60):
        return self._impl(getattr(self, 'gui', None)).get_details(search_result, timeout=timeout)

    def config_widget(self):
        return self._impl(getattr(self, 'gui', None)).config_widget()

    def save_settings(self, config_widget):
        return self._impl(getattr(self, 'gui', None)).save_settings(config_widget)

    def customization_help(self, gui=None):
        try:
            return self._impl(gui or getattr(self, 'gui', None)).customization_help(gui)
        except Exception:
            return None
