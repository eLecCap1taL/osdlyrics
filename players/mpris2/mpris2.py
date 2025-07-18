# -*- coding: utf-8 -*-
#
# Copyright (C) 2011  Tiger Soldier
#
# This file is part of OSD Lyrics.
#
# OSD Lyrics is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OSD Lyrics is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OSD Lyrics.  If not, see <https://www.gnu.org/licenses/>.
#
import logging

import dbus
import dbus.service
import dbus.types

from osdlyrics.consts import (DAEMON_MPRIS2_NAME, MPRIS2_OBJECT_PATH,
                              MPRIS2_PLAYER_INTERFACE, MPRIS2_PREFIX)
from osdlyrics.metadata import Metadata
from osdlyrics.player_proxy import (CAPS, REPEAT, STATUS, BasePlayer,
                                    BasePlayerProxy, PlayerInfo)

import threading
from gi.repository import GLib
import time

# These constants map flags/enums from MPRIS2-specific values to OSDLyrics values.
CAPS_MAP = {
    'CanGoNext': CAPS.NEXT,
    'CanGoPrevious': CAPS.PREV,
    'CanPlay': CAPS.PLAY,
    'CanPause': CAPS.PAUSE,
    'CanSeek': CAPS.SEEK,
}


class ProxyObject(BasePlayerProxy):
    """ The DBus object for MPRIS2 player proxy
    """

    def __init__(self):
        """
        """
        super().__init__('Mpris2')

    def _get_player_from_bus_names(self, names):
        """ Returns list of `PlayerInfo` objects according to names.

        The bus names in names with prefix of MPRIS2_PREFIX will be treated as MPRIS2
        players. The suffix of these names will be treated as player name

        Arguments:
        - `names`: list of bus names
        """
        return [
            PlayerInfo.from_name(name[len(MPRIS2_PREFIX):])
            for name in names
            if name.startswith(MPRIS2_PREFIX) and name != DAEMON_MPRIS2_NAME
        ]

    def do_list_active_players(self):
        return self._get_player_from_bus_names(map(str, self.connection.list_names()))

    def do_list_supported_players(self):
        return self.do_list_activatable_players()

    def do_list_activatable_players(self):
        players = self._get_player_from_bus_names(map(str, self.connection.list_activatable_names()))
        return players

    def do_connect_player(self, player_name):
        player = Mpris2Player(self, player_name)
        return player


class Mpris2Player(BasePlayer):
    def __init__(self, proxy, player_name):
        logging.warning("CAP yes i init1")
        super().__init__(proxy, player_name)
        self._properties_changed_signal = None
        self._seeked_signal = None
        self._name_watch = None
        self.refresh_spotify_status_freqcnt = 0
        try:
            mpris2_object_path = MPRIS2_PREFIX + player_name
            self._player = dbus.Interface(
                self.connection.get_object(mpris2_object_path,
                                           MPRIS2_OBJECT_PATH),
                MPRIS2_PLAYER_INTERFACE)
            self._player_prop = dbus.Interface(
                self.connection.get_object(mpris2_object_path,
                                           MPRIS2_OBJECT_PATH),
                dbus.PROPERTIES_IFACE)
            self._properties_changed_signal = (
                self._player_prop.connect_to_signal(
                    'PropertiesChanged', self._player_properties_changed))
            self._seeked_signal = self._player.connect_to_signal(
                'Seeked', self._player_seeked)
            self._name_watch = self.connection.watch_name_owner(
                mpris2_object_path, self._name_lost)
            
            self._start_sync_spotify_status()
        except Exception:
            self.disconnect()

    def refresh_spotify_status(self):
        try:
            if self.get_status() == STATUS.PLAYING:
                # 发一个play命令，强制刷新 position
                self._player.Play()
                # logging.warning("CAP synced")
            else:
                pass
                # logging.warning("CAP not sync, stopped")
        except Exception as e:
            pass
            # logging.warning("CAP Sync play failed: %s", e)
        return False

    def _start_sync_spotify_status(self):
        def poll_loop():
            while True:

                if(self.refresh_spotify_status_freqcnt>0):
                    self.refresh_spotify_status_freqcnt-=1
                    # logging.warning("CAP high freq check")
                    time.sleep(0.3)  # fast check
                else:
                    time.sleep(2)  # 每2秒检查一次

                self.refresh_spotify_status()
        threading.Thread(target=poll_loop, daemon=True).start()

    def _name_lost(self, name):
        if name:
            return
        self.disconnect()

    def disconnect(self):
        if self._properties_changed_signal:
            self._properties_changed_signal.remove()
            self._properties_changed_signal = None
        if self._name_watch:
            self._name_watch.cancel()
            self._name_watch = None
        self._player = None
        self._player_prop = None
        BasePlayer.disconnect(self)

    def _player_properties_changed(self, iface, changed, invalidated):
        self.refresh_spotify_status_freqcnt+=10

        caps_props = ['CanGoNext', 'CanGoPrevious', 'CanPlay', 'CanPause', 'CanSeek']
        prop_map = {'PlaybackStatus': 'status_changed',
                    'LoopStatus': 'repeat_changed',
                    'Shuffle': 'shuffle_changed',
                    'Metadata': 'track_changed',
                    }
        # status_props = ['PlaybackStatus', 'LoopStatus', 'Shuffle']
        logging.debug('Status changed: %s', changed)
        for caps in caps_props:
            if caps in changed:
                self.caps_changed()
                break
        for prop_name, method in prop_map.items():
            if prop_name in changed:
                getattr(self, method)()

    def _player_seeked(self, position):
        # logging.warning("CAP %s",position)
        self.position_changed(position//1000)
        # self.position_changed(((position // 1000)+position / 1000)/2)

    @property
    def object_path(self):
        return self._object_path

    @property
    def connected(self):
        return self._connected

    def next(self):
        self._player.Next()

    def prev(self):
        self._player.Previous()

    def pause(self):
        self._player.Pause()

    def stop(self):
        self._player.Stop()

    def play(self):
        self._player.Play()

    def set_repeat(self, repeat):
        try:
            if repeat == REPEAT.TRACK:
                self._player_prop.Set(MPRIS2_PLAYER_INTERFACE, 'LoopStatus',
                                      'Track')
            elif repeat == REPEAT.ALL:
                self._player_prop.Set(MPRIS2_PLAYER_INTERFACE, 'LoopStatus',
                                      'Playlist')
            else:
                self._player_prop.Set(MPRIS2_PLAYER_INTERFACE, 'LoopStatus',
                                      'None')
        except Exception:
            pass

    def get_status(self):
        playback_dict = {'Playing': STATUS.PLAYING,
                         'Paused': STATUS.PAUSED,
                         'Stopped': STATUS.STOPPED}
        try:
            return playback_dict[self._player_prop.Get(MPRIS2_PLAYER_INTERFACE,
                                                       'PlaybackStatus')]
        except Exception as e:
            logging.error('Failed to get status: %s', e)
            return STATUS.PLAYING

    def get_repeat(self):
        repeat_dict = {'None': REPEAT.NONE,
                       'Track': REPEAT.TRACK,
                       'Playlist': REPEAT.ALL}
        try:
            return repeat_dict[self._player_prop.Get(MPRIS2_PLAYER_INTERFACE,
                                                     'LoopStatus')]
        except Exception:
            return REPEAT.NONE

    def get_shuffle(self):
        try:
            return bool(self._player_prop.Get(MPRIS2_PLAYER_INTERFACE,
                                              'Shuffle'))
        except Exception:
            return False

    def get_metadata(self):
        metadata = self._player_prop.Get(MPRIS2_PLAYER_INTERFACE, 'Metadata')
        return Metadata.from_mpris2(metadata)

    def get_caps(self):
        caps = set()
        for k, cap in CAPS_MAP.items():
            if self._player_prop.Get(MPRIS2_PLAYER_INTERFACE, k):
                caps.add(cap)
        return caps

    def set_volume(self, volume):
        self._player_prop.Set(MPRIS2_PLAYER_INTERFACE, 'Volume', volume)

    def get_volume(self):
        return self._player_prop.Get(MPRIS2_PLAYER_INTERFACE, 'Volume')

    def set_position(self, time_in_mili):
        track_id = self._player_prop.Get(
            MPRIS2_PLAYER_INTERFACE, 'Metadata')['mpris:trackid']
        self._player.SetPosition(track_id, time_in_mili * 1000)

    def get_position(self):
        return self._player_prop.Get(MPRIS2_PLAYER_INTERFACE, 'Position') // 1000


def run():
    mpris2 = ProxyObject()
    logging.warning("CAP ok 222 runnig")
    mpris2.run()


if __name__ == '__main__':
    run()
