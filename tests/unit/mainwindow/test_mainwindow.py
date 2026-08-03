# SPDX-FileCopyrightText: Oskar Stenman <oskar@cetex.se>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.mainwindow.mainwindow._WindowOcclusionWatcher."""

from unittest.mock import Mock

import pytest

from qutebrowser.qt.core import QEvent, QObject

from qutebrowser.mainwindow import mainwindow


class _FakeWindowHandle:

    """Stand-in for a QWindow handle, exposing only what the watcher reads."""

    def __init__(self, exposed):
        self.exposed = exposed

    def isExposed(self):
        return self.exposed

    def installEventFilter(self, _obj):
        pass


class _FakeWindow(QObject):

    """Stand-in for MainWindow, exposing only what the watcher reads."""

    def __init__(self, handle, tab):
        super().__init__()
        self.win_id = 0
        self._handle = handle
        self.tabbed_browser = Mock()
        self.tabbed_browser.widget.currentWidget.return_value = tab

    def windowHandle(self):
        return self._handle


@pytest.fixture
def make_watcher(fake_web_tab, mocker):
    """Build an installed _WindowOcclusionWatcher over a real fake tab."""
    def _make(exposed):
        handle = _FakeWindowHandle(exposed)
        tab = fake_web_tab()
        mocker.patch.object(tab, 'set_page_visibility')
        window = _FakeWindow(handle, tab)
        watcher = mainwindow._WindowOcclusionWatcher(window)
        watcher.install()
        return watcher, window, tab
    return _make


def _expose_event():
    return QEvent(QEvent.Type.Expose)


class TestWindowOcclusionWatcher:

    def test_occlusion_hides_current_tab(self, make_watcher):
        watcher, window, tab = make_watcher(exposed=True)
        window.windowHandle().exposed = False

        watcher.eventFilter(window.windowHandle(), _expose_event())

        tab.set_page_visibility.assert_called_once_with(False)

    def test_re_exposure_shows_current_tab(self, make_watcher):
        watcher, window, tab = make_watcher(exposed=False)
        tab.set_page_visibility.reset_mock()  # drop install()'s initial hide

        window.windowHandle().exposed = True
        watcher.eventFilter(window.windowHandle(), _expose_event())

        tab.set_page_visibility.assert_called_once_with(True)

    def test_repeated_occlusion_events_flip_visibility_once(self, make_watcher):
        watcher, window, tab = make_watcher(exposed=True)
        window.windowHandle().exposed = False

        watcher.eventFilter(window.windowHandle(), _expose_event())
        watcher.eventFilter(window.windowHandle(), _expose_event())

        tab.set_page_visibility.assert_called_once_with(False)

    def test_tab_switch_while_occluded_hides_new_tab(self, make_watcher, fake_web_tab, mocker):
        watcher, window, _tab = make_watcher(exposed=True)
        window.windowHandle().exposed = False
        watcher.eventFilter(window.windowHandle(), _expose_event())
        new_tab = fake_web_tab()
        mocker.patch.object(new_tab, 'set_page_visibility')
        window.tabbed_browser.widget.currentWidget.return_value = new_tab

        watcher._on_current_changed(1)

        new_tab.set_page_visibility.assert_called_once_with(False)

    def test_tab_switch_while_exposed_leaves_visibility_alone(self, make_watcher, fake_web_tab, mocker):
        watcher, window, _tab = make_watcher(exposed=True)
        new_tab = fake_web_tab()
        mocker.patch.object(new_tab, 'set_page_visibility')
        window.tabbed_browser.widget.currentWidget.return_value = new_tab

        watcher._on_current_changed(1)

        new_tab.set_page_visibility.assert_not_called()
