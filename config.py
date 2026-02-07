from typing import Dict

from calibre_plugins.store_annas_archive.constants import (DEFAULT_MIRRORS, SearchConfiguration, Order, Content, Access,
                                                           FileType, Source, Language)

try:
    from qt.core import (Qt, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox, QScrollArea,
                         QAbstractScrollArea, QComboBox, QCheckBox, QSizePolicy, QListWidget, QListWidgetItem,
                         QAbstractItemView, QShortcut, QKeySequence, QLineEdit)
except (ImportError, ModuleNotFoundError):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (QWidget, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox, QScrollArea,
                                 QAbstractScrollArea, QComboBox, QCheckBox, QSizePolicy, QListWidget, QListWidgetItem,
                                 QAbstractItemView, QShortcut, QLineEdit)
    from PyQt5.QtGui import QKeySequence

load_translations()


class MirrorsList(QListWidget):
    def __init__(self, parent=...):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        self._check_last_changed = False
        self.itemChanged.connect(self.add_mirror)

        self.delete_pressed = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        self.delete_pressed.activated.connect(self.delete_item)

    def delete_item(self):
        if self.currentRow() != self.count() - 1:
            self.takeItem(self.currentRow())

    def load_mirrors(self, mirrors):
        self._check_last_changed = False
        for mirror in mirrors:
            item = QListWidgetItem(mirror, self)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._add_last_list_item()
        self._check_last_changed = True

    def _add_last_list_item(self):
        item = QListWidgetItem('', self)
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsEnabled)

    def dropEvent(self, event):
        y = event.pos().y()
        if (self.count() < 5 and y <= (self.count() * 16) - 10) or (self.count() >= 5 and y <= 70):
            return super().dropEvent(event)

    def add_mirror(self, item):
        if self._check_last_changed and self.count() == self.indexFromItem(item).row() + 1:
            if item.text():
                self._check_last_changed = False
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
                self._add_last_list_item()
                self._check_last_changed = True

    def get_mirrors(self) -> list:
        return [
            item for i in range(self.count())
            if (item := str(self.item(i).text()))
        ]


class ConfigWidget(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.resize(635, 780)

        main_layout = QVBoxLayout(self)

        search_options = QGroupBox(_('Search options'), self)
        search_options.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        search_grid = QGridLayout(search_options)
        search_grid.setContentsMargins(3, 3, 3, 3)

        ordering_label = QLabel(_('Ordering:'), search_options)
        ordering_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        search_grid.addWidget(ordering_label, 0, 0)
        order = QComboBox(search_options)
        for txt, value in Order.options:
            order.addItem(txt, value)
        order.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        search_grid.addWidget(order, 0, 1)
        self.order = Order(order)

        self.search_options: Dict[str, SearchConfiguration] = {self.order.config_option: self.order}

        # TODO: lay the options out better
        search_grid.addWidget(self._make_cbx_group(search_options, Content()), 1, 0)
        search_grid.addWidget(self._make_cbx_group(search_options, FileType()), 2, 0)
        search_grid.addWidget(self._make_cbx_group(search_options, Access()), 1, 1)
        search_grid.addWidget(self._make_cbx_group(search_options, Source()), 2, 1)
        search_grid.addWidget(self._make_cbx_group(search_options, Language(), scrollbar=True), 1, 2, 2, 1)

        main_layout.addWidget(search_options)

        horizontal_layout = QHBoxLayout()

        link_options = QGroupBox(_('Download link options'), self)
        link_options.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        link_layout = QVBoxLayout(link_options)
        link_layout.setContentsMargins(6, 6, 6, 6)
        self.url_extension = QCheckBox(_('Verify url extension'), link_options)
        self.url_extension.setToolTip(_('Verify that the each download url ends with correct extension for the format'))
        link_layout.addWidget(self.url_extension)
        self.content_type = QCheckBox(_('Verify Content-Type'), link_options)
        self.content_type.setToolTip(_(
            'Get the header of each site and verify that it has an \'application\' content type'))
        link_layout.addWidget(self.content_type)
        self.close_after_download = QCheckBox(_('Close store window after download completes (inline mode only)'), link_options)
        self.close_after_download.setToolTip(_('When using the inline web view, close the store window once a download finishes'))
        link_layout.addWidget(self.close_after_download)
        horizontal_layout.addWidget(link_options)

        mirrors = QGroupBox(_('Mirrors'), self)
        layout = QVBoxLayout(mirrors)
        layout.setContentsMargins(1, 1, 1, 1)
        self.mirrors = MirrorsList(mirrors)
        layout.addWidget(self.mirrors)
        horizontal_layout.addWidget(mirrors)

        main_layout.addLayout(horizontal_layout)

        self.open_external = QCheckBox(_('Open store in external web browser'), self)
        main_layout.addWidget(self.open_external)

        # Bookworm integration
        bookworm_box = QGroupBox(_('Bookworm wanted list'), self)
        bookworm_layout = QGridLayout(bookworm_box)
        bookworm_layout.setContentsMargins(6, 6, 6, 6)

        self.bookworm_enabled = QCheckBox(_('Enable Bookworm integration'), bookworm_box)
        self.bookworm_enabled.setToolTip(_('Fetch wanted books from a Bookworm instance via /api/calibre/wanted'))
        bookworm_layout.addWidget(self.bookworm_enabled, 0, 0, 1, 2)

        self.bookworm_sidebar = QCheckBox(_('Show Bookworm sidebar'), bookworm_box)
        self.bookworm_sidebar.setToolTip(_('Show a wanted-list sidebar next to the store window'))
        bookworm_layout.addWidget(self.bookworm_sidebar, 1, 0, 1, 2)

        bw_url_label = QLabel(_('API base URL'), bookworm_box)
        bw_url_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bookworm_layout.addWidget(bw_url_label, 2, 0)
        self.bookworm_url = QLineEdit(bookworm_box)
        self.bookworm_url.setPlaceholderText('https://bookworm.example.com')
        bookworm_layout.addWidget(self.bookworm_url, 2, 1)

        bw_token_label = QLabel(_('API token (optional)'), bookworm_box)
        bw_token_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bookworm_layout.addWidget(bw_token_label, 3, 0)
        self.bookworm_token = QLineEdit(bookworm_box)
        self.bookworm_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.bookworm_token.setPlaceholderText(_('Leave blank if your instance is public'))
        bookworm_layout.addWidget(self.bookworm_token, 3, 1)

        main_layout.addWidget(bookworm_box)

        self.load_settings()

    def _make_cbx_group(self, parent, option: SearchConfiguration, scrollbar: bool = False):
        box = QGroupBox(_(option.name), parent)
        vertical_layout = QVBoxLayout(box)
        if scrollbar:
            vertical_layout.setSpacing(0)
            vertical_layout.setContentsMargins(0, 0, 0, 0)

            scroll_area = QScrollArea(box)
            scroll_area.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            scroll_area.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)

            cbx_parent = QWidget()
            cbx_parent.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            top_vertical = vertical_layout
            vertical_layout = QVBoxLayout(cbx_parent)
        else:
            cbx_parent = box

        vertical_layout.setSpacing(3)
        vertical_layout.setContentsMargins(3, 3, 3, 3)

        for name, type_ in option.options:
            check_box = QCheckBox(cbx_parent)
            check_box.setText(name)
            vertical_layout.addWidget(check_box)
            option.checkboxes[type_] = check_box
        self.search_options[option.config_option] = option
        if scrollbar:
            scroll_area.setWidget(cbx_parent)
            top_vertical.addWidget(scroll_area)
        return box

    def load_settings(self):
        config = self.store.config

        self.open_external.setChecked(config.get('open_external', False))
        self.mirrors.load_mirrors(config.get('mirrors', DEFAULT_MIRRORS))

        bookworm = config.get('bookworm', {})
        self.bookworm_enabled.setChecked(bookworm.get('enabled', False))
        self.bookworm_sidebar.setChecked(bookworm.get('sidebar', True))
        self.bookworm_url.setText(bookworm.get('base_url', ''))
        self.bookworm_token.setText(bookworm.get('token', ''))

        search_opts = config.get('search', {})
        for configuration in self.search_options.values():
            configuration.load(search_opts.get(configuration.config_option, configuration.default))

        link_opts = config.get('link', {})
        self.url_extension.setChecked(link_opts.get('url_extension', True))
        self.content_type.setChecked(link_opts.get('content_type', False))
        ui_opts = config.get('ui', {})
        self.close_after_download.setChecked(ui_opts.get('close_after_download', False))

    def save_settings(self):
        self.store.config['open_external'] = self.open_external.isChecked()
        self.store.config['mirrors'] = self.mirrors.get_mirrors()

        self.store.config['search'] = {
            configuration.config_option: configuration.to_save()
            for configuration in self.search_options.values()
        }
        self.store.config['link'] = {
            'url_extension': self.url_extension.isChecked(),
            'content_type': self.content_type.isChecked()
        }
        self.store.config['ui'] = {
            'close_after_download': self.close_after_download.isChecked()
        }
        self.store.config['bookworm'] = {
            'enabled': self.bookworm_enabled.isChecked(),
            'sidebar': self.bookworm_sidebar.isChecked(),
            'base_url': self.bookworm_url.text().strip(),
            'token': self.bookworm_token.text().strip()
        }
