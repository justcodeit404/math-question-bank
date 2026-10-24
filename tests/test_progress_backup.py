import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='node not installed')
def test_progress_backup_keeps_notes_and_fill_answers():
    result = subprocess.run(
        [NODE, str(ROOT / 'tests' / 'test_progress_backup.mjs')],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'test_progress_backup: ok' in result.stdout
