# SPDX-FileCopyrightText: Oskar Stenman <oskar@cetex.se>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for qutebrowser.browser.webengine.tabhistory."""

import struct

import pytest

from qutebrowser.qt.core import QUrl

from qutebrowser.browser.webengine import tabhistory
from qutebrowser.misc.sessions import TabHistoryItem as Item


def _first_page_state(data):
    """Extract the first entry's page state from a serialized stream.

    Stream layout (QDataStream, big-endian): stream version, entry count
    and current index as int32, then per entry a length-prefixed URL, a
    length-prefixed UTF-16 title and the length-prefixed page state.
    """
    pos = 12
    url_len = int.from_bytes(data[pos:pos + 4], 'big')
    pos += 4 + url_len
    title_len = int.from_bytes(data[pos:pos + 4], 'big')
    pos += 4 + title_len
    ps_len = int.from_bytes(data[pos:pos + 4], 'big')
    pos += 4
    return data[pos:pos + ps_len]


@pytest.mark.parametrize('url', [
    QUrl('https://www.example.com/'),
    QUrl('http://example.com/%E2%80%A6'),
    QUrl('https://example.com/?foo=bar#frag'),
    QUrl('http://[::1]:8080/path'),
    QUrl('data:text/html,<b>hi</b>'),
])
def test_page_state_is_url_only_pickle(url):
    """Entries must carry Chromium's version -1 (URL-only) PageState.

    Wire format per ReadPageState in Chromium's
    page_state_serialization.cc: a base::Pickle (uint32 payload size
    header) containing an int32 version of -1 and a length-prefixed URL
    string, writes padded to 4 bytes, all little-endian.
    """
    _stream, data, _user_data = tabhistory.serialize(
        [Item(url, 'title', active=True)])
    blob = _first_page_state(bytes(data))
    payload_size, version, url_len = struct.unpack_from('<IiI', blob, 0)
    assert payload_size == len(blob) - 4
    assert payload_size % 4 == 0
    assert version == -1
    assert blob[12:12 + url_len] == bytes(url.toEncoded())
    padding = blob[12 + url_len:]
    assert len(padding) < 4
    assert set(padding) <= {0}
