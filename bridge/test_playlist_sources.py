from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import qqbridge as bridge

class PlaylistSourceTests(unittest.TestCase):
    def test_netease_playlists_are_not_gated_by_qq_login(self):
        with patch.object(bridge,'reload_auth',return_value={'logged_in':False,'uin':'0','cookie':''}), \
             patch.object(bridge.qqmusic,'user_playlists',return_value=[{'disstid':'123','name':'NetEase list','count':2}]) as fetch:
            status,body=bridge.api_playlists({'src':'ne'})
        self.assertEqual(status,200)
        self.assertEqual(body['source'],'ne')
        self.assertTrue(body['logged_in'])
        self.assertEqual(body['playlists'][0]['count'],2)
        fetch.assert_called_once()

    def test_qq_without_credentials_does_not_query_netease(self):
        with patch.object(bridge,'reload_auth',return_value={'logged_in':False,'uin':'0','cookie':''}), \
             patch.object(bridge.qqmusic,'user_playlists') as fetch:
            _,body=bridge.api_playlists({'src':'qq'})
        self.assertFalse(body['logged_in'])
        self.assertEqual(body['source'],'qq')
        fetch.assert_not_called()

    def test_default_qq_source_still_loads_qq_playlists(self):
        with patch.object(bridge,'reload_auth',return_value={'logged_in':True,'uin':'123','cookie':'test-cookie'}), \
             patch.object(bridge.qqmusic,'user_playlists',return_value=[]):
            _,body=bridge.api_playlists({})
        self.assertEqual(body['source'],'qq')
        self.assertTrue(body['logged_in'])

unittest.main(verbosity=2)
