from contextlib import closing
import json
from http.client import RemoteDisconnected
from math import ceil
import re
from typing import Generator
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import urlopen, Request

from calibre import browser
from calibre.gui2 import open_url
from calibre.gui2.store import StorePlugin
from calibre.gui2.store.search_result import SearchResult
from calibre.gui2.store.web_store_dialog import WebStoreDialog
from calibre_plugins.store_annas_archive.constants import DEFAULT_MIRRORS, RESULTS_PER_PAGE, SearchOption
from lxml import html

try:
    from qt.core import Qt, QUrl
    from qt.widgets import (QDialog, QWidget, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QSplitter)
except (ImportError, ModuleNotFoundError):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (QDialog, QWidget, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout, QPushButton,
                                 QLabel, QSplitter)
    from PyQt5.Qt import QUrl

# Optional web engine view for inline store dialog
try:
    from qt.webenginewidgets import QWebEngineView
except Exception:
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except Exception:
        QWebEngineView = None
if QWebEngineView is None:
    try:
        # calibre ships a compat importer that works across Qt versions
        from calibre.gui2.qt_imports import QWebEngineView as _CalibreQWebEngineView
        QWebEngineView = _CalibreQWebEngineView
    except Exception:
        QWebEngineView = None

SearchResults = Generator[SearchResult, None, None]


class AnnasArchiveStore(StorePlugin):

    def __init__(self, gui, name, config=None, base_plugin=None):
        super().__init__(gui, name, config, base_plugin)
        self.working_mirror = None
        # Keep references to detached sidebars so they are not GC'd.
        self._sidebar_windows = []

    def _search(self, url: str, max_results: int, timeout: int) -> SearchResults:
        br = browser()
        doc = None
        counter = max_results

        for page in range(1, ceil(max_results / RESULTS_PER_PAGE) + 1):
            mirrors = self.config.get('mirrors', DEFAULT_MIRRORS)
            if self.working_mirror is not None:
                mirrors.remove(self.working_mirror)
                mirrors.insert(0, self.working_mirror)
            for mirror in mirrors:
                with closing(br.open(url.format(base=mirror, page=page), timeout=timeout)) as resp:
                    if resp.code < 500 or resp.code > 599:
                        self.working_mirror = mirror
                        doc = html.fromstring(resp.read())
                        break
            if doc is None:
                self.working_mirror = None
                raise Exception('No working mirrors of Anna\'s Archive found.')

            books = doc.xpath('//table/tr')
            for book in books:
                if counter <= 0:
                    break

                columns = book.findall("td")
                s = SearchResult()

                cover = columns[0].xpath('./a[@tabindex="-1"]')
                if cover:
                    cover = cover[0]
                else:
                    continue
                s.detail_item = cover.get('href', '').split('/')[-1]
                if not s.detail_item:
                    continue

                s.cover_url = ''.join(cover.xpath('(./span/img/@src)[1]'))
                s.title = ''.join(columns[1].xpath('./a/span/text()'))
                s.author = ''.join(columns[2].xpath('./a/span/text()'))
                s.formats = ''.join(columns[9].xpath('./a/span/text()')).upper()

                s.price = '$0.00'
                s.drm = SearchResult.DRM_UNLOCKED

                counter -= 1
                yield s

    def search(self, query, max_results=10, timeout=60) -> SearchResults:
        search_opts = self.config.get('search', {})

        def build_url(term: str) -> str:
            url = f'{{base}}/search?page={{page}}&q={quote_plus(term)}&display=table'
            for option in SearchOption.options:
                value = search_opts.get(option.config_option, ())
                if isinstance(value, str):
                    value = (value,)
                for item in value:
                    url += f'&{option.url_param}={item}'
            return url

        # Special query to pull Bookworm wanted list and search for the first match of each item.
        if self._is_bookworm_query(query):
            yield from self._search_bookworm_wanted(build_url, max_results, timeout)
            return
        # Bookworm picker UI lets the user choose which wanted item to search.
        if self._is_bookworm_picker_query(query):
            yield from self._search_bookworm_pick(build_url, max_results, timeout)
            return

        # Allow searching a list of ISBNs (comma or newline separated). If the query looks like a
        # list of ISBN-like tokens, issue sequential searches and stop after max_results.
        raw_terms = [q.strip() for q in re.split(r'[,\n]+', query) if q.strip()]
        terms = []
        seen = set()
        for term in raw_terms:
            if term not in seen:
                seen.add(term)
                terms.append(term)

        isbn_list = len(terms) > 1 and all(re.fullmatch(r'[0-9Xx-]+', term) for term in terms)

        if isbn_list:
            remaining = max_results
            for term in terms:
                if remaining <= 0:
                    break
                for result in self._search(build_url(term), remaining, timeout):
                    remaining -= 1
                    yield result
            return

        url = build_url(query)
        yield from self._search(url, max_results, timeout)

    def _is_bookworm_query(self, query: str) -> bool:
        """
        Users can type `bookworm:wanted` in the store search bar to fetch their Bookworm wanted list.
        """
        if not self.config.get('bookworm', {}).get('enabled', False):
            return False
        normalized = query.strip().lower()
        return normalized in {'bookworm:wanted', 'bookworm wanted', 'bw:wanted', ':wanted'}

    def _is_bookworm_picker_query(self, query: str) -> bool:
        """
        Users can type `bookworm:pick` to open a picker list and choose which wanted item to search.
        """
        if not self.config.get('bookworm', {}).get('enabled', False):
            return False
        normalized = query.strip().lower()
        return normalized in {'bookworm:pick', 'bookworm:list', 'bw:pick', ':pick'}

    def _fetch_bookworm_wanted(self, timeout: int):
        cfg = self.config.get('bookworm', {})
        base = cfg.get('base_url', '').strip().rstrip('/')
        if not base:
            raise Exception('Bookworm base URL is not configured.')

        url = f'{base}/api/calibre/wanted'
        headers = {'Accept': 'application/json'}
        token = cfg.get('token', '').strip()
        if token:
            headers['Authorization'] = f'Bearer {token}'

        try:
            with urlopen(Request(url, headers=headers), timeout=timeout) as resp:
                payload = json.load(resp)
        except (HTTPError, URLError, TimeoutError, RemoteDisconnected) as exc:
            raise Exception(f'Failed to fetch Bookworm wanted list: {exc}')

        items = payload.get('items', [])
        if not isinstance(items, list):
            raise Exception('Bookworm response did not include an \"items\" list.')
        def sort_key(item):
            title = str(item.get('title') or '').strip().lower()
            authors = item.get('authors') or []
            first_author = str(authors[0]).strip().lower() if authors else ''
            return (title, first_author)
        return sorted(items, key=sort_key)

    @staticmethod
    def _bookworm_terms(item):
        terms = []
        for isbn in item.get('isbns') or ():
            cleaned = isbn.replace('-', '').strip()
            if cleaned and cleaned not in terms:
                terms.append(cleaned)

        title = item.get('title', '').strip()
        authors = item.get('authors') or []
        if title:
            if authors:
                terms.append(f'{title} {authors[0]}')
            terms.append(title)
        return terms

    def _pick_bookworm_item(self, items):
        if not items:
            return None

        dlg = QDialog(self.gui)
        dlg.setWindowTitle('Bookworm wanted list')
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel('Pick a wanted book to search on Anna\'s Archive'))

        list_widget = QListWidget(dlg)
        for item in items:
            title = item.get('title', '(untitled)')
            authors = ', '.join(item.get('authors') or [])
            display = f'{title} | {authors}' if authors else title
            lw_item = QListWidgetItem(display)
            lw_item.setData(Qt.ItemDataRole.UserRole, self._bookworm_terms(item))
            list_widget.addItem(lw_item)
        list_widget.setMinimumWidth(520)
        list_widget.setMinimumHeight(320)
        list_widget.setCurrentRow(0)
        layout.addWidget(list_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton('Cancel', dlg)
        ok_btn = QPushButton('Search', dlg)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dlg.reject)
        ok_btn.clicked.connect(dlg.accept)
        list_widget.itemDoubleClicked.connect(lambda _: dlg.accept())

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        item = list_widget.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # --- Sidebar helpers ---

    def _maybe_show_bookworm_sidebar(self, dialog):
        bookworm_cfg = self.config.get('bookworm', {})
        if not (bookworm_cfg.get('enabled') and bookworm_cfg.get('sidebar', True)):
            return
        try:
            items = self._fetch_bookworm_wanted(timeout=15)
        except Exception:
            return
        # Use a detached sidebar to avoid Qt binding mismatches; keep a strong ref.
        sidebar = BookwormSidebar(self, dialog, items, self._navigate_store_from_sidebar)
        self._sidebar_windows.append(sidebar)
        try:
            sidebar.destroyed.connect(lambda: self._sidebar_windows.remove(sidebar) if sidebar in self._sidebar_windows else None)  # type: ignore[attr-defined]
        except Exception:
            pass
        sidebar.show()
        # Try to stick the sidebar to the left edge of the store dialog.
        try:
            geom = dialog.frameGeometry()
            sidebar.move(geom.x() - sidebar.width() - 6, geom.y())
        except Exception:
            pass

    def _navigate_store_from_sidebar(self, dialog, terms):
        if not terms:
            return
        search_url = self._build_sidebar_search_url(terms[0])
        if not search_url:
            return
        # Try to load in the inline view first.
        try:
            if hasattr(dialog, 'view'):
                dialog.view.load(QUrl(search_url))
                return
        except Exception:
            pass

        # Otherwise, open a new Calibre store window (not the external browser).
        if self.working_mirror is None:
            self.working_mirror = self.config.get('mirrors', DEFAULT_MIRRORS)[0]
        try:
            d = WebStoreDialog(self.gui, self.working_mirror, dialog or self.gui, search_url)
            d.setWindowTitle(self.name)
            d.set_tags(self.config.get('tags', ''))
            d.exec()
            return
        except Exception:
            pass

        # Last resort: external browser.
        open_url(QUrl(search_url))

    def _build_sidebar_search_url(self, term: str) -> str:
        search_opts = self.config.get('search', {})
        base = self.working_mirror or self.config.get('mirrors', DEFAULT_MIRRORS)[0]
        url = f'{base}/search?page=1&q={quote_plus(term)}&display=table'
        for option in SearchOption.options:
            value = search_opts.get(option.config_option, ())
            if isinstance(value, str):
                value = (value,)
            for item in value:
                url += f'&{option.url_param}={item}'
        return url

    def _open_inline_store(self, url: str, parent) -> bool:
        """
        Try to show the store (and Bookworm sidebar, if enabled) in one window
        using a Qt WebEngine view. Falls back to the default WebStoreDialog if
        WebEngine is unavailable.
        """
        if QWebEngineView is None:
            return False

        bookworm_cfg = self.config.get('bookworm', {})
        show_sidebar = bookworm_cfg.get('enabled', False) and bookworm_cfg.get('sidebar', True)

        try:
            items = self._fetch_bookworm_wanted(timeout=15) if show_sidebar else []
        except Exception:
            items = []

        try:
            dlg = InlineStoreDialog(self, parent or self.gui, url, items, show_sidebar, self._navigate_store_from_sidebar)
        except Exception:
            return False
        dlg.exec()
        return True

    def _search_bookworm_wanted(self, build_url, max_results: int, timeout: int) -> SearchResults:
        wanted_items = self._fetch_bookworm_wanted(timeout)
        remaining = max_results

        for item in wanted_items:
            if remaining <= 0:
                break

            terms = self._bookworm_terms(item)

            found = False
            for term in terms:
                for result in self._search(build_url(term), 1, timeout):
                    remaining -= 1
                    found = True
                    yield result
                    break
                if remaining <= 0:
                    break
                if found:
                    break

    def _search_bookworm_pick(self, build_url, max_results: int, timeout: int) -> SearchResults:
        wanted_items = self._fetch_bookworm_wanted(timeout)
        terms = self._pick_bookworm_item(wanted_items)
        if not terms:
            return

        remaining = max_results
        for term in terms:
            if remaining <= 0:
                break
            for result in self._search(build_url(term), 1, timeout):
                remaining -= 1
                yield result
                break

    def open(self, gui=None, parent=None, detail_item=None, external=False):
        if detail_item:
            url = self._get_url(detail_item)
        else:
            if self.working_mirror is not None:
                url = self.working_mirror
            else:
                url = self.config.get('mirrors', DEFAULT_MIRRORS)[0]
        if external or self.config.get('open_external', False):
            open_url(QUrl(url))
        else:
            if self._open_inline_store(url, parent):
                return
            d = WebStoreDialog(self.gui, self.working_mirror, parent, url)
            d.setWindowTitle(self.name)
            d.set_tags(self.config.get('tags', ''))
            self._maybe_show_bookworm_sidebar(d)
            d.exec()

    def get_details(self, search_result: SearchResult, timeout=60):
        if not search_result.formats:
            return

        expected_ext = '.' + search_result.formats.lower()

        link_opts = self.config.get('link', {})
        url_extension = link_opts.get('url_extension', True)
        content_type = link_opts.get('content_type', False)

        br = browser()
        if self.working_mirror is None:
            self.working_mirror = self.config.get('mirrors', DEFAULT_MIRRORS)[0]
        with closing(br.open(self._get_url(search_result.detail_item), timeout=timeout)) as f:
            doc = html.fromstring(f.read())

        def has_expected_extension(url: str) -> bool:
            """
            Only enforce an extension check if there is an extension present in the path.
            Some mirrors use extension-less URLs (fast/slow downloads), which should be allowed.
            """
            params_split = url.split('?', 1)
            url_without_params = params_split[0]
            filename = url_without_params.rsplit('/', 1)[-1]
            if '.' not in filename:
                return True
            return url_without_params.lower().endswith(expected_ext)

        for link in doc.xpath('//div[@id="md5-panel-downloads"]//a[contains(@class, "js-download-link")]'):
            url = link.get('href')
            if not url:
                continue
            # Skip AA-hosted fast/slow links that sit behind a JS challenge.
            if '/fast_download/' in url or '/slow_download/' in url:
                continue
            link_text = ' '.join(link.itertext()).strip()
            link_text_lower = link_text.lower()

            if 'libgen.li' in link_text_lower or 'libgen.li' in url:
                url = self._get_libgen_link(url, br)
                link_text = link_text or 'Libgen.li'
            elif 'libgen.rs' in link_text_lower or 'libgen.rs' in url:
                url = self._get_libgen_nonfiction_link(url, br)
                link_text = link_text or 'Libgen.rs'
            elif 'sci-hub' in link_text_lower or 'scihub' in url:
                url = self._get_scihub_link(url, br)
                link_text = link_text or 'Sci-Hub'
            elif 'z-library' in link_text_lower or 'zlib' in link_text_lower:
                url = self._get_zlib_link(url, br)
                link_text = link_text or 'Z-Library'

            if not url:
                continue

            if url.startswith('/'):
                url = f"{self.working_mirror}{url}"

            # Takes longer, but more accurate
            if content_type:
                try:
                    with urlopen(Request(url, method='HEAD'), timeout=timeout) as resp:
                        if resp.info().get_content_maintype() != 'application':
                            continue
                except (HTTPError, URLError, TimeoutError, RemoteDisconnected):
                    pass
            elif url_extension:
                # Speeds it up by checking the extension of the url.
                # Might miss a direct url that doesn't end with the extension
                if not has_expected_extension(url):
                    continue
            search_result.downloads[f"{link_text}.{search_result.formats}"] = url

    @staticmethod
    def _get_libgen_link(url: str, br) -> str:
        with closing(br.open(url)) as resp:
            doc = html.fromstring(resp.read())
            scheme, _, host, _ = resp.geturl().split('/', 3)
        url = ''.join(doc.xpath('//a[h2[text()="GET"]]/@href'))
        return f"{scheme}//{host}/{url}"

    @staticmethod
    def _get_libgen_nonfiction_link(url: str, br) -> str:
        with closing(br.open(url)) as resp:
            doc = html.fromstring(resp.read())
        url = ''.join(doc.xpath('//h2/a[text()="GET"]/@href'))
        return url

    @staticmethod
    def _get_scihub_link(url, br):
        with closing(br.open(url)) as resp:
            doc = html.fromstring(resp.read())
            scheme, _ = resp.geturl().split('/', 1)
        url = ''.join(doc.xpath('//embed[@id="pdf"]/@src'))
        if url:
            return scheme + url

    @staticmethod
    def _get_zlib_link(url, br):
        with closing(br.open(url)) as resp:
            doc = html.fromstring(resp.read())
            scheme, _, host, _ = resp.geturl().split('/', 3)
        url = ''.join(doc.xpath('//a[contains(@class, "addDownloadedBook")]/@href'))
        if url:
            return f"{scheme}//{host}/{url}"

    def _get_url(self, md5):
        return f"{self.working_mirror}/md5/{md5}"

    def config_widget(self):
        from calibre_plugins.store_annas_archive.config import ConfigWidget
        return ConfigWidget(self)

    def save_settings(self, config_widget):
        config_widget.save_settings()



class BookwormSidebar(QWidget):
    def __init__(self, plugin, store_dialog, items, select_callback):
        # Tie lifetime to the store dialog when possible, without triggering
        # binding mismatches on some Calibre builds.
        parent = store_dialog if isinstance(store_dialog, QDialog) else None
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle('Bookworm wanted list')
        if parent is None:
            self.setWindowFlag(Qt.WindowType.Tool)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.select_callback = select_callback
        self.store_dialog = store_dialog

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(QLabel('Bookworm wanted'))

        self.list_widget = QListWidget(self)
        for item in items:
            title = item.get('title', '(untitled)')
            authors = ', '.join(item.get('authors') or [])
            display = f'{title} | {authors}' if authors else title
            lw_item = QListWidgetItem(display)
            lw_item.setToolTip(display)
            lw_item.setData(Qt.ItemDataRole.UserRole, item)
            self.list_widget.addItem(lw_item)
        self.list_widget.itemDoubleClicked.connect(self._on_pick)
        self.list_widget.itemClicked.connect(self._on_pick)
        self.list_widget.setMinimumWidth(520)
        self.list_widget.setMinimumHeight(420)
        layout.addWidget(self.list_widget)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close_btn = QPushButton('Close', self)
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

        try:
            self.resize(640, 520)
        except Exception:
            pass

        # Close automatically if the parent dialog is destroyed.
        if parent is not None:
            try:
                parent.destroyed.connect(self.close)
            except Exception:
                pass

    def _on_pick(self, item):
        if not item:
            return
        terms = self.plugin._bookworm_terms(item.data(Qt.ItemDataRole.UserRole))
        # Prefer the store dialog (inline or standalone) as navigation target.
        target_dialog = self.store_dialog if self.store_dialog is not None else self
        self.select_callback(target_dialog, terms)


class InlineStoreDialog(QDialog):
    """
    Simple wrapper dialog that hosts both the Bookworm sidebar and a WebEngine view
    so everything lives in a single window when supported.
    """
    def __init__(self, plugin, parent, url, items, show_sidebar, select_callback):
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle(plugin.name)
        ui_opts = plugin.config.get('ui', {})
        self.close_after_download = ui_opts.get('close_after_download', False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        if show_sidebar:
            self.sidebar = BookwormSidebar(plugin, self, items, select_callback)
            splitter.addWidget(self.sidebar)
        else:
            self.sidebar = None

        self.view = QWebEngineView(self)
        self.view.load(QUrl(url))
        try:
            profile = self.view.page().profile()
            profile.downloadRequested.connect(self._on_download_requested)
        except Exception:
            pass
        splitter.addWidget(self.view)
        # Favor web view space; sidebar gets a smaller fraction if present.
        splitter.setStretchFactor(0, 0 if show_sidebar else 1)
        splitter.setStretchFactor(1 if show_sidebar else 0, 1)

        layout.addWidget(splitter)

    def _on_download_requested(self, download):
        # Close after the first download finishes if the option is enabled.
        try:
            download.finished.connect(self._maybe_close_after_download)
        except Exception:
            try:
                # Fallback for PyQt versions without finished signal
                download.stateChanged.connect(
                    lambda state: getattr(download, 'DownloadCompleted', None) is not None
                    and state == download.DownloadCompleted
                    and self._maybe_close_after_download()
                )
            except Exception:
                pass

    def _maybe_close_after_download(self):
        if self.close_after_download:
            self.accept()

    def _on_pick(self, item):
        if not item:
            return
        terms = self.plugin._bookworm_terms(item.data(Qt.ItemDataRole.UserRole))
        self.select_callback(self.store_dialog, terms)
