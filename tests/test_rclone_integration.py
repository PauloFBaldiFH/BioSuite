"""Transporte rclone real para alias local, sem credenciais ou serviços externos."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from biosuite import backups
from biosuite.backup_format import archive_tree, seal, verify

@unittest.skipUnless(shutil.which('rclone'),'rclone não instalado: integração de transporte opcional')
class RcloneIntegrationTests(unittest.TestCase):
    def test_copy_readback_and_download_preserve_payload_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);remote=root/'remote';remote.mkdir();source=root/'backup-fixture';source.mkdir()
            tree=root/'data';tree.mkdir();(tree/'sequence.dat').write_text('ACGT\n')
            for name in ('data.tar','code.tar','config.tar'):archive_tree(tree,source/name)
            (source/'database.dump').write_bytes(b'fixture-transport-only')
            (source/'inventory.json').write_text('[]')
            seal(source,{'mode':'native','galaxy_release':'26.1.2','pg_major':17,'database_bytes':20,'created_utc':'test'})
            config=root/'rclone.conf';config.write_text('[localtest]\ntype = alias\nremote = '+str(remote)+'\n')
            with patch.dict(os.environ,{'RCLONE_CONFIG':str(config)}):
                result=backups.upload(source,'localtest:copies',output=lambda _:None)
                self.assertTrue(result['readback_verified'])
                fetched=backups.download(result['destination'],root/'downloads',output=lambda _:None)
            info=verify(Path(fetched['downloaded']))
            self.assertEqual(info['payloads'],verify(source)['payloads'])
            self.assertFalse((remote/'copies/backup-fixture/rclone-upload.log').exists())
            self.assertEqual(fetched['database_restore'],'not_tested')
