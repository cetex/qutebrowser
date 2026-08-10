# SPDX-FileCopyrightText: Freya Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.misc.sessions."""

import logging

import pytest
import yaml
from qutebrowser.qt.core import QUrl, QPoint, QByteArray, QObject

from qutebrowser.misc import sessions
from qutebrowser.misc.sessions import TabHistoryItem as Item
from qutebrowser.utils import objreg, qtutils, urlmatch
from qutebrowser.browser.webkit import tabhistory


pytestmark = pytest.mark.qt_log_ignore('QIODevice::read.*: device not open')

webengine_refactoring_xfail = pytest.mark.xfail(
    True, reason='Broke during QtWebEngine refactoring, will be fixed after '
                 'sessions are refactored too.')


@pytest.fixture
def sess_man(tmp_path):
    """Fixture providing a SessionManager."""
    return sessions.SessionManager(base_path=str(tmp_path))


class TestInit:

    @pytest.fixture(autouse=True)
    def cleanup(self, monkeypatch):
        monkeypatch.setattr(sessions, 'session_manager', None)
        yield
        try:
            objreg.delete('session-manager')
        except KeyError:
            pass

    @pytest.mark.parametrize('create_dir', [True, False])
    def test_with_standarddir(self, tmp_path, monkeypatch, create_dir):
        monkeypatch.setattr(sessions.standarddir, 'data',
                            lambda: str(tmp_path))
        session_dir = tmp_path / 'sessions'
        if create_dir:
            session_dir.mkdir()

        sessions.init()

        assert session_dir.exists()
        assert sessions.session_manager._base_path == str(session_dir)


def test_did_not_load(sess_man):
    assert not sess_man.did_load


class TestExists:

    @pytest.mark.parametrize('absolute', [True, False])
    def test_existent(self, tmp_path, absolute):
        session_dir = tmp_path / 'sessions'
        abs_session = tmp_path / 'foo.yml'
        rel_session = session_dir / 'foo.yml'

        session_dir.mkdir()
        abs_session.touch()
        rel_session.touch()

        man = sessions.SessionManager(str(session_dir))

        if absolute:
            name = str(abs_session)
        else:
            name = 'foo'

        assert man.exists(name)

    @pytest.mark.parametrize('absolute', [True, False])
    def test_inexistent(self, tmp_path, absolute):
        man = sessions.SessionManager(str(tmp_path))

        if absolute:
            name = str(tmp_path / 'foo')
        else:
            name = 'foo'

        assert not man.exists(name)


@webengine_refactoring_xfail
class TestSaveTab:

    @pytest.mark.parametrize('is_active', [True, False])
    def test_active(self, sess_man, webview, is_active):
        data = sess_man._save_tab(webview, is_active)
        if is_active:
            assert data['active']
        else:
            assert 'active' not in data

    def test_no_history(self, sess_man, webview):
        data = sess_man._save_tab(webview, active=False)
        assert not data['history']


class FakeMainWindow(QObject):

    """Helper class for the fake_main_window fixture.

    A fake MainWindow which provides a saveGeometry method.

    Needs to be a QObject so sip.isdeleted works.
    """

    def __init__(self, geometry, win_id, parent=None):
        super().__init__(parent)
        self._geometry = QByteArray(geometry)
        self.win_id = win_id

    def saveGeometry(self):
        return self._geometry


@pytest.fixture
def fake_window(tabbed_browser_stubs):
    """Fixture which provides a fake main windows with a tabbedbrowser."""
    win0 = FakeMainWindow(b'fake-geometry-0', win_id=0)
    objreg.register('main-window', win0, scope='window', window=0)
    yield
    objreg.delete('main-window', scope='window', window=0)


class TestSaveAll:

    def test_no_history(self, sess_man):
        # FIXME can this ever actually happen?
        assert not objreg.window_registry
        data = sess_man._save_all()
        assert not data['windows']

    @webengine_refactoring_xfail
    def test_no_active_window(self, sess_man, fake_window, stubs,
                              monkeypatch):
        qapp = stubs.FakeQApplication(active_window=None)
        monkeypatch.setattr(sessions, 'QApplication', qapp)
        sess_man._save_all()


@pytest.mark.parametrize('arg, config, current, expected', [
    ('foo', None, None, 'foo'),
    (sessions.default, 'foo', None, 'foo'),
    (sessions.default, None, 'foo', 'foo'),
    (sessions.default, None, None, 'default'),
])
def test_get_session_name(config_stub, sess_man, arg, config, current,
                          expected):
    config_stub.val.session.default_name = config
    sess_man.current = current
    assert sess_man._get_session_name(arg) == expected


class TestSave:

    @pytest.fixture
    def fake_history(self, stubs, tabbed_browser_stubs, monkeypatch, webview):
        """Fixture which provides a window with a fake history."""
        win = FakeMainWindow(b'fake-geometry-0', win_id=0)
        objreg.register('main-window', win, scope='window', window=0)

        browser = tabbed_browser_stubs[0]
        qapp = stubs.FakeQApplication(active_window=win)
        monkeypatch.setattr(sessions, 'QApplication', qapp)

        def set_data(items):
            history = browser.widgets()[0].page().history()
            stream, _data, user_data = tabhistory.serialize(items)
            qtutils.deserialize_stream(stream, history)
            for i, data in enumerate(user_data):
                history.itemAt(i).setUserData(data)

        yield set_data

        objreg.delete('main-window', scope='window', window=0)
        objreg.delete('tabbed-browser', scope='window', window=0)

    def test_no_state_config(self, sess_man, tmp_path, state_config):
        session_path = tmp_path / 'foo.yml'
        sess_man.save(str(session_path))
        assert 'session' not in state_config['general']

    def test_last_window_session_none(self, caplog, sess_man, tmp_path):
        session_path = tmp_path / 'foo.yml'
        with caplog.at_level(logging.ERROR):
            sess_man.save(str(session_path), last_window=True)

        msg = "last_window_session is None while saving!"
        assert caplog.messages == [msg]
        assert not session_path.exists()

    def test_last_window_session(self, sess_man, tmp_path):
        sess_man.save_last_window_session()
        session_path = tmp_path / 'foo.yml'
        sess_man.save(str(session_path), last_window=True)
        data = session_path.read_text('utf-8')
        assert data == 'windows: []\n'

    @pytest.mark.parametrize('exception', [
        OSError('foo'), UnicodeEncodeError('ascii', '', 0, 2, 'foo'),
        yaml.YAMLError('foo')])
    def test_fake_exception(self, mocker, sess_man, tmp_path, exception):
        mocker.patch('qutebrowser.misc.sessions.yaml.dump',
                     side_effect=exception)

        with pytest.raises(sessions.SessionError, match=str(exception)):
            sess_man.save(str(tmp_path / 'foo.yml'))

        assert not list(tmp_path.glob('*'))

    def test_load_next_time(self, tmp_path, state_config, sess_man):
        session_path = tmp_path / 'foo.yml'
        sess_man.save(str(session_path), load_next_time=True)
        assert state_config['general']['session'] == str(session_path)

    @webengine_refactoring_xfail
    def test_utf_8_invalid(self, tmp_path, sess_man, fake_history):
        """Make sure data containing invalid UTF8 raises SessionError."""
        session_path = tmp_path / 'foo.yml'
        fake_history([Item(QUrl('http://www.qutebrowser.org/'), '\ud800',
                           active=True)])

        try:
            sess_man.save(str(session_path))
        except sessions.SessionError:
            # This seems to happen on some systems only?!
            pass
        else:
            data = session_path.read_text('utf-8')
            assert r'title: "\uD800"' in data

    def _set_data(self, browser, tab_id, items):
        """Helper function for test_long_output."""
        history = browser.widgets()[tab_id].page().history()
        stream, _data, user_data = tabhistory.serialize(items)
        qtutils.deserialize_stream(stream, history)
        for i, data in enumerate(user_data):
            history.itemAt(i).setUserData(data)


class FakeHistoryPrivate:

    """A fake for AbstractHistoryPrivate, recording what got loaded."""

    def __init__(self):
        self.loaded_items = None
        self.loaded_discarded_items = None
        self.raise_error = None

    def load_items(self, items, discard=False):
        if self.raise_error is not None:
            raise self.raise_error
        if discard:
            self.loaded_discarded_items = items
        else:
            self.loaded_items = items


class FakeHistory:

    def __init__(self):
        self.private_api = FakeHistoryPrivate()


class FakeSignal:

    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class FakeTabData:

    def __init__(self):
        self.pinned = False


class FakeTab:

    """A tab fake matching the new_tab API _load_tab actually uses."""

    def __init__(self, discard_supported=False):
        self.data = FakeTabData()
        self.title_changed = FakeSignal()
        self.history = FakeHistory()
        self._discard_supported = discard_supported

    def discard_supported(self):
        return self._discard_supported


@pytest.fixture
def fake_tab():
    return FakeTab()


class TestBuildHistoryEntries:

    """Tests for SessionManager._build_history_entries."""

    def test_no_history(self, sess_man):
        entries, active_idx, pinned = sess_man._build_history_entries(
            {'history': []})
        assert entries == []
        assert active_idx is None
        assert pinned is False

    @pytest.mark.parametrize('key, val, expected', [
        ('zoom', 1.23, 1.23),
        ('scroll-pos', {'x': 23, 'y': 42}, QPoint(23, 42)),
    ])
    @pytest.mark.parametrize('in_main_data', [True, False])
    def test_user_data(self, sess_man, key, val, expected, in_main_data):
        item = {'url': 'http://www.example.com/', 'title': 'foo'}

        if in_main_data:
            # This information got saved in the main data instead of saving it
            # per item - make sure the old format can still be read
            # https://github.com/qutebrowser/qutebrowser/issues/728
            d = {'history': [item], key: val}
        else:
            item[key] = val
            d = {'history': [item]}

        entries, _active_idx, _pinned = sess_man._build_history_entries(d)
        assert len(entries) == 1
        assert entries[0].user_data[key] == expected

    @pytest.mark.parametrize('original_url', ['http://example.org/', None])
    def test_urls(self, sess_man, original_url):
        url = 'http://www.example.com/'
        item = {'url': url, 'title': 'foo'}

        if original_url is None:
            expected = QUrl(url)
        else:
            item['original-url'] = original_url
            expected = QUrl(original_url)

        entries, _active_idx, _pinned = sess_man._build_history_entries(
            {'history': [item]})
        assert len(entries) == 1
        assert entries[0].url == QUrl(url)
        assert entries[0].original_url == expected

    def test_active_idx(self, sess_man):
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo'},
            {'url': 'https://example.org/', 'title': 'bar', 'active': True},
        ]}
        entries, active_idx, _pinned = sess_man._build_history_entries(data)
        assert active_idx == 1
        assert entries[active_idx].url == QUrl('https://example.org/')

    def test_no_active_entry(self, sess_man):
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo'},
        ]}
        _entries, active_idx, _pinned = sess_man._build_history_entries(data)
        assert active_idx is None

    def test_pinned_last_entry_wins(self, sess_man):
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo', 'pinned': True},
            {'url': 'https://example.org/', 'title': 'bar', 'pinned': False},
        ]}
        _entries, _active_idx, pinned = sess_man._build_history_entries(data)
        assert pinned is False


class TestInjectBackStub:

    """Tests for sessions.inject_back_stub."""

    def test_splices_after_active_entry(self):
        items = [Item(QUrl('https://example.com/'), 'foo', active=True)]

        sessions.inject_back_stub(items, 0)

        assert not items[0].active
        assert items[1].active
        assert items[1].url == QUrl('qute://back#foo')
        assert items[1].title == 'foo'

    def test_noop_if_already_stub(self):
        items = [Item(QUrl('qute://back#foo'), 'foo', active=True)]

        sessions.inject_back_stub(items, 0)

        assert len(items) == 1
        assert items[0].active


class TestLoadTab:

    """Tests for SessionManager._load_tab.

    A tab that isn't unloaded returns its entries for deferred loading
    (see _run_deferred_loads) instead of loading them synchronously.
    """

    def test_no_history(self, sess_man, config_stub, fake_tab):
        entries = sess_man._load_tab(fake_tab, {'history': []})
        assert entries == []
        assert fake_tab.history.private_api.loaded_items is None

    def test_load_fail(self, sess_man, config_stub, fake_tab):
        """A stub/discard load failure raises synchronously, unlike a
        deferred one (see TestRunDeferredLoads)."""
        config_stub.val.session.lazy_restore = True
        fake_tab.history.private_api.raise_error = ValueError
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo', 'active': True},
        ]}
        with pytest.raises(sessions.SessionError):
            sess_man._load_tab(fake_tab, data)

    def test_pinned(self, sess_man, config_stub, fake_tab):
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo', 'pinned': True},
        ]}
        sess_man._load_tab(fake_tab, data)
        assert fake_tab.data.pinned is True

    def test_active_entry_emits_title_changed(self, sess_man, config_stub,
                                              fake_tab):
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo', 'active': True},
        ]}
        sess_man._load_tab(fake_tab, data)
        assert fake_tab.title_changed.emitted == [('foo',)]

    def test_lazy_restore_inserts_back_stub(self, sess_man, config_stub,
                                            fake_tab):
        config_stub.val.session.lazy_restore = True
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo', 'active': True},
        ]}

        sess_man._load_tab(fake_tab, data)

        items = fake_tab.history.private_api.loaded_items
        assert len(items) == 2
        assert not items[0].active
        assert items[1].active
        assert items[1].url == QUrl('qute://back#foo')

    def test_lazy_restore_off_no_stub(self, sess_man, config_stub, fake_tab):
        config_stub.val.session.lazy_restore = False
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo', 'active': True},
        ]}

        entries = sess_man._load_tab(fake_tab, data)

        assert len(entries) == 1
        assert fake_tab.history.private_api.loaded_items is None

    def test_no_active_entry_lazy_restore_no_crash(self, sess_man,
                                                   config_stub, fake_tab):
        """#7696: a saved history can have no entry marked active (e.g. an
        invalid current URL at save time). Combined with lazy_restore, the
        per-tab decision must not crash looking up the (nonexistent) active
        entry; it should just return the entries for a normal, deferred
        load.
        """
        config_stub.val.session.lazy_restore = True
        data = {'history': [
            {'url': 'https://example.com/', 'title': 'foo'},
        ]}

        entries = sess_man._load_tab(fake_tab, data)

        assert len(entries) == 1
        assert not entries[0].active
        assert fake_tab.history.private_api.loaded_items is None


@pytest.fixture
def discard_mode_config(config_stub):
    """A config_stub with lazy_restore and content.lifecycle discarding on."""
    config_stub.val.session.lazy_restore = True
    config_stub.val.content.lifecycle.enabled = True
    config_stub.val.content.lifecycle.discard_delay = 500
    return config_stub


class TestLoadTabDiscardMode:

    """Tests for _load_tab's per-tab normal/stub/discard decision."""

    def _data(self, active=False, url='https://example.com/'):
        return {'active': active, 'history': [
            {'url': url, 'title': 'foo', 'active': True},
        ]}

    def _assert_outcome(self, tab, entries, outcome):
        items = tab.history.private_api.loaded_items
        discarded = tab.history.private_api.loaded_discarded_items
        if outcome == 'stub':
            assert entries is None
            assert len(items) == 2
            assert items[1].url.toString() == 'qute://back#foo'
            assert discarded is None
        elif outcome == 'discard':
            assert entries is None
            assert items is None
            assert len(discarded) == 1
        elif outcome == 'normal':
            # Loaded normally means deferred: the entries are returned for
            # the caller to load, not written to the tab synchronously.
            assert len(entries) == 1
            assert items is None
            assert discarded is None

    @pytest.mark.parametrize(
        'enabled, discard_delay, discard_supported, focused, '
        'pattern_override, outcome', [
            # Default config (discard_delay=-1) stubs, never eager-discards.
            (True, -1, True, False, None, 'stub'),
            # A background tab is discarded once discarding is configured.
            (True, 500, True, False, None, 'discard'),
            # The focused tab always loads normally, never discarded.
            (True, 500, True, True, None, 'normal'),
            # A per-URL override disabling the lifecycle exempts the tab.
            (True, 500, True, False,
             ('content.lifecycle.enabled', False), 'normal'),
            # Lifecycle disabled globally loads every tab normally too.
            (False, 500, True, False, None, 'normal'),
            # WebKit (discard_supported=False) always stubs, never discards.
            (True, 500, False, False, None, 'stub'),
            # A per-URL discard_delay=-1 exempts the tab entirely (no
            # discard, no stub), uniformly regardless of engine support.
            (True, 500, True, False,
             ('content.lifecycle.discard_delay', -1), 'normal'),
            (True, 500, False, False,
             ('content.lifecycle.discard_delay', -1), 'normal'),
        ],
        ids=['default', 'background-discard', 'focused', 'url-exempted',
             'disabled-globally', 'discard-unsupported',
             'url-discard-delay-capable', 'url-discard-delay-legacy'])
    def test_decision_matrix(self, sess_man, config_stub, enabled,
                             discard_delay, discard_supported, focused,
                             pattern_override, outcome):
        config_stub.val.session.lazy_restore = True
        config_stub.val.content.lifecycle.enabled = enabled
        config_stub.val.content.lifecycle.discard_delay = discard_delay
        if pattern_override is not None:
            name, value = pattern_override
            pattern = urlmatch.UrlPattern('https://example.com/*')
            config_stub.set_obj(name, value, pattern=pattern)
        tab = FakeTab(discard_supported=discard_supported)

        entries = sess_man._load_tab(tab, self._data(active=focused))

        self._assert_outcome(tab, entries, outcome)

    def test_default_config_still_stubs(self, sess_man, config_stub):
        """Pinned regression test: default config still stubs.

        This has regressed three times: the global discard_delay default
        is -1, the same value that also means "exempt" as a URL pattern -
        they must not collapse into the same case. Untouched defaults plus
        lazy_restore must keep producing the qute://back stub.
        """
        config_stub.val.session.lazy_restore = True
        tab = FakeTab(discard_supported=True)

        entries = sess_man._load_tab(tab, self._data(active=False))

        self._assert_outcome(tab, entries, 'stub')

    def test_empty_history_loads_normally(self, sess_man, discard_mode_config):
        tab = FakeTab(discard_supported=True)

        entries = sess_man._load_tab(tab, {'active': False, 'history': []})

        assert entries == []
        assert tab.history.private_api.loaded_items is None


class FakeCurrentTabChanged:

    """A fake for TabbedBrowser.current_tab_changed (connect/disconnect
    only, no real Qt signal machinery)."""

    def __init__(self):
        self._slot = None

    def connect(self, slot):
        self._slot = slot

    def disconnect(self, slot):
        assert slot is self._slot
        self._slot = None

    def emit(self, tab):
        self._slot(tab)


class FakeTabbedBrowser:

    def __init__(self):
        self.current_tab_changed = FakeCurrentTabChanged()


class TestRunDeferredLoads:

    """Tests for SessionManager._run_deferred_loads."""

    @pytest.fixture(autouse=True)
    def immediate_timer(self, monkeypatch):
        """Run queued loads right away instead of waiting out the delay."""
        monkeypatch.setattr(sessions.QTimer, 'singleShot',
                            lambda _ms, func: func())
        monkeypatch.setattr(sessions.sip, 'isdeleted', lambda _tab: False)

    def test_priority_order(self, sess_man):
        """The focused tab (priority 0) loads before the rest, which load
        in their original tab order."""
        tabs = [FakeTab() for _ in range(3)]
        pending = [(1, 1, tabs[1], ['b']), (0, 0, tabs[0], ['a']),
                  (1, 2, tabs[2], ['c'])]
        pending.sort(key=lambda entry: entry[:2])

        sess_man._run_deferred_loads(FakeTabbedBrowser(), pending)

        assert tabs[0].history.private_api.loaded_items == ['a']
        assert tabs[1].history.private_api.loaded_items == ['b']
        assert tabs[2].history.private_api.loaded_items == ['c']

    def test_failed_load_logs_and_continues(self, sess_man, caplog):
        bad_tab = FakeTab()
        bad_tab.history.private_api.raise_error = ValueError('boom')
        good_tab = FakeTab()
        pending = [(0, 0, bad_tab, ['x']), (1, 1, good_tab, ['y'])]

        with caplog.at_level(logging.ERROR):
            sess_man._run_deferred_loads(FakeTabbedBrowser(), pending)

        assert good_tab.history.private_api.loaded_items == ['y']
        assert caplog.messages == ['Deferred session load failed: boom']

    def test_deleted_tab_skipped(self, sess_man, monkeypatch):
        deleted_tab = FakeTab()
        good_tab = FakeTab()
        monkeypatch.setattr(sessions.sip, 'isdeleted',
                            lambda tab: tab is deleted_tab)
        pending = [(0, 0, deleted_tab, ['x']), (1, 1, good_tab, ['y'])]

        sess_man._run_deferred_loads(FakeTabbedBrowser(), pending)

        assert deleted_tab.history.private_api.loaded_items is None
        assert good_tab.history.private_api.loaded_items == ['y']

    def test_focus_jump_loads_immediately(self, sess_man, monkeypatch):
        """Switching to a tab still in the queue loads it right away,
        ahead of its turn; the chain still drains what's left after."""
        scheduled = []
        monkeypatch.setattr(sessions.QTimer, 'singleShot',
                            lambda _ms, func: scheduled.append(func))
        tabs = [FakeTab() for _ in range(3)]
        pending = [(0, 0, tabs[0], ['a']), (1, 1, tabs[1], ['b']),
                  (1, 2, tabs[2], ['c'])]
        tabbed_browser = FakeTabbedBrowser()

        sess_man._run_deferred_loads(tabbed_browser, pending)
        tabbed_browser.current_tab_changed.emit(tabs[2])
        assert tabs[1].history.private_api.loaded_items is None
        scheduled.pop(0)()  # let the chain's pending tick run

        assert tabs[0].history.private_api.loaded_items == ['a']
        assert tabs[2].history.private_api.loaded_items == ['c']
        assert tabs[1].history.private_api.loaded_items == ['b']

    def test_focus_jump_empties_queue_before_chain_tick(self, sess_man,
                                                        monkeypatch):
        """The chain's already-scheduled tick may fire after a focus jump
        has drained the rest of the queue; it should just disconnect."""
        scheduled = []
        monkeypatch.setattr(sessions.QTimer, 'singleShot',
                            lambda _ms, func: scheduled.append(func))
        tabs = [FakeTab() for _ in range(2)]
        pending = [(0, 0, tabs[0], ['a']), (1, 1, tabs[1], ['b'])]
        tabbed_browser = FakeTabbedBrowser()

        sess_man._run_deferred_loads(tabbed_browser, pending)
        tabbed_browser.current_tab_changed.emit(tabs[1])
        scheduled.pop(0)()  # the pending tick finds an empty queue

        assert tabs[0].history.private_api.loaded_items == ['a']
        assert tabs[1].history.private_api.loaded_items == ['b']
        assert tabbed_browser.current_tab_changed._slot is None


class TestListSessions:

    def test_no_sessions(self, tmp_path):
        sess_man = sessions.SessionManager(str(tmp_path))
        assert not sess_man.list_sessions()

    def test_with_sessions(self, tmp_path):
        (tmp_path / 'foo.yml').touch()
        (tmp_path / 'bar.yml').touch()
        sess_man = sessions.SessionManager(str(tmp_path))
        assert sess_man.list_sessions() == ['bar', 'foo']

    def test_with_other_files(self, tmp_path):
        (tmp_path / 'foo.yml').touch()
        (tmp_path / 'bar.html').touch()
        sess_man = sessions.SessionManager(str(tmp_path))
        assert sess_man.list_sessions() == ['foo']
