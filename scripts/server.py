#!/usr/bin/env python3
"""Small wrapper around http.server that tracks its own PID.

Usage:
    python scripts/server.py --port 8123 --open http://localhost:8123/index.html
    python scripts/server.py --stop
"""
import argparse
import http.server
import os
import re
import signal
import socketserver
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / 'temp' / 'server.pid'

VIEWER_TEMPLATE = ROOT / 'templates' / 'math-bank.html'
VIEWER_COMMON = ROOT.parent / 'viewer-common'
DATA_SCRIPT_PLACEHOLDER = '<!-- DATA_SCRIPT -->'
DATA_SCRIPT_TAG = '<script src="data.js"></script>'
VC_VER_PLACEHOLDER = '@VC_VER@'
CROPS_VER_PLACEHOLDER = '@CROPS_VER@'


def viewer_common_ver() -> str:
    """与 scripts/generate_viewer.py 相同口径：viewer-common 运行时文件内容 hash。"""
    import hashlib

    h = hashlib.sha256()
    for name in ('pdf-export.js', 'pdf-lib.min.js', 'platform-sync.js', 'question-notes.js', 'scratch-ink.js',
                 'scratch-pad.js', 'scratch-pad.css', 'storage.js'):
        f = VIEWER_COMMON / name
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:8]


def crops_ver(book_dir: Path) -> str:
    """与 scripts/generate_viewer.py 相同口径：answer_crops 文件名+大小 hash。"""
    import hashlib

    h = hashlib.sha256()
    crops = book_dir / 'answer_crops'
    if crops.exists():
        for f in sorted(crops.glob('*.png')):
            h.update(f.name.encode())
            h.update(str(f.stat().st_size).encode())
    return h.hexdigest()[:8]


class BankHandler(http.server.SimpleHTTPRequestHandler):
    """Serve math-bank viewer from a single template, injecting per-book data.js."""

    def do_GET(self):
        path = self.path.split('?')[0]
        # URL-decode is handled by base class; use raw path parts
        if path.rstrip('/').endswith('/math-bank/index.html'):
            if VIEWER_TEMPLATE.exists():
                body = VIEWER_TEMPLATE.read_text(encoding='utf-8')
                body = body.replace(DATA_SCRIPT_PLACEHOLDER, DATA_SCRIPT_TAG)
                body = body.replace(VC_VER_PLACEHOLDER, viewer_common_ver())
                book_dir = (ROOT / unquote(path).lstrip('/').replace('/', os.sep)).parent
                body = body.replace(CROPS_VER_PLACEHOLDER, crops_ver(book_dir))
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body.encode('utf-8'))
                return
        return super().do_GET()


def is_running(pid):
    """Check whether a process with the given PID exists."""
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    return os.path.exists(f'/proc/{pid}')


def start(port, open_url=None):
    PID_FILE.parent.mkdir(exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding='utf-8')

    handler = BankHandler
    with socketserver.TCPServer(('', port), handler) as httpd:
        print(f'Server running at http://localhost:{port}/')
        if open_url:
            # Open browser without blocking
            subprocess.Popen(['start', '', open_url], shell=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def stop():
    if not PID_FILE.exists():
        print('Server PID file not found.')
        return
    pid_text = PID_FILE.read_text(encoding='utf-8').strip()
    if not pid_text:
        PID_FILE.unlink(missing_ok=True)
        return
    pid = int(pid_text)
    if not is_running(pid):
        print(f'Server PID {pid} is not running.')
        PID_FILE.unlink(missing_ok=True)
        return
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, False, pid)
        kernel32.TerminateProcess(handle, 0)
        kernel32.CloseHandle(handle)
    else:
        os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    print(f'Stopped server PID {pid}.')


def main():
    parser = argparse.ArgumentParser(description='Simple PID-tracked HTTP server')
    parser.add_argument('--port', type=int, default=8123)
    parser.add_argument('--open', default=None, help='URL to open in browser')
    parser.add_argument('--stop', action='store_true', help='Stop running server')
    args = parser.parse_args()

    if args.stop:
        stop()
    else:
        start(args.port, args.open)


if __name__ == '__main__':
    main()
