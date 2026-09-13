#!/usr/bin/env python3
"""One-shot launch transport and sequencing checks, without production access."""
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

NATIVE = Path(__file__).resolve().parents[1] / 'native'
sys.path.insert(0, str(NATIVE))
from launch_babel import remote_command
from release_core import ReleaseError
from release_launch import wait_job


class LaunchTests(unittest.TestCase):
    def test_wait_does_not_mistake_queued_or_recovery_for_success(self):
        with patch('release_launch.load', side_effect=[{'job': 'a'}, {'phase': 'queued'}, {'phase': 'schema_ready'}]), patch('release_launch.info', return_value={'ActiveState': 'inactive'}), patch('release_launch.time.sleep'):
            self.assertEqual(wait_job('schema_ready'), 'a')
        with patch('release_launch.load', side_effect=[{'job': 'a'}, {'phase': 'rolled_back'}]), patch('release_launch.info', return_value={'ActiveState': 'inactive'}):
            with self.assertRaises(ReleaseError): wait_job('complete')

    def test_frozen_archive_transport_rejects_tampering_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'bundle.tar'
            payload = b"from pathlib import Path;Path(__file__).with_name('success').write_text('verified')"
            with tarfile.open(archive, 'w') as tar:
                member = tarfile.TarInfo('release_launch.py'); member.size = len(payload)
                tar.addfile(member, io.BytesIO(payload))
            code = shlex.split(remote_command(archive))[-1]
            code = code.replace('/home/heyx/VSP-Sub2API/bundle.tar', str(archive))
            code = code.replace('base.stat().st_uid==0', f'base.stat().st_uid=={os.getuid()}')
            for case in ('valid', 'tampered', 'symlink'):
                base = root / case; base.mkdir(mode=0o700)
                if case == 'tampered':
                    raw = archive.read_bytes(); archive.write_bytes(b'X' + raw[1:])
                if case == 'symlink':
                    target = root / 'target'; archive.rename(target); archive.symlink_to(target)
                result = subprocess.run([sys.executable, '-I', '-c', code.replace("'/var/backups'", repr(str(base)))], capture_output=True, timeout=10)
                self.assertEqual(result.returncode == 0, case == 'valid')
                self.assertEqual(bool(list(base.rglob('success'))), case == 'valid')

    def test_catalog_failure_cannot_prevent_app_activation(self):
        # Static ordering supplements the transaction tests: catalog publication
        # is independent and happens only after the new App is verified live.
        source = (NATIVE / 'release_launch.py').read_text()
        self.assertLess(source.index("execute(LIB / 'release_schema.py', 'activate'"), source.index("publish_catalog(source /"))
        self.assertIn("'--accept-unrehearsed'", source)
        self.assertIn('dir_fd=directory', source)


if __name__ == '__main__': unittest.main(verbosity=2)
