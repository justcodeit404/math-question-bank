"""Shared utilities used across question bank scripts."""
import json
import os
import tempfile
from pathlib import Path


def write_json_atomic(path, data, indent=2, ensure_ascii=False):
    """Write JSON atomically: temp file + os.replace.

    Prevents data corruption if the process is interrupted mid-write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f'{path.name}.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise


def write_text_atomic(path, text, encoding='utf-8'):
    """Write text atomically: temp file + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f'{path.name}.tmp')
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise
