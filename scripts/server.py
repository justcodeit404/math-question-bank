#!/usr/bin/env python3
"""Small wrapper around http.server that tracks its own PID.

Usage:
    python scripts/server.py --port 8123 --open http://localhost:8123/index.html
    python scripts/server.py --stop
"""
import argparse
import http.server
import os
import signal
import socketserver
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / 'temp' / 'server.pid'


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

    handler = http.server.SimpleHTTPRequestHandler
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
