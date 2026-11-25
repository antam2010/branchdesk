"""Bounded binary subprocess transport on POSIX and Windows."""
import os
import signal
import subprocess
import threading


def stop(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    if process.poll() is None: process.kill()
    process.wait()


def run(command, *, data=None, env=None, cwd=None, timeout=90, limit=16*1024*1024, preview=False):
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    proc = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **flags)
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()
    def reader(pipe, buf):
        try:
            while True:
                chunk = os.read(pipe.fileno(), 65536)
                if not chunk: break
                room = max(0, limit + 1 - len(buf))
                buf.extend(chunk[:room])
                if len(buf) > limit: overflow.set()
        except OSError: pass
    def writer():
        try: proc.stdin.write(data); proc.stdin.flush()
        except (OSError, BrokenPipeError): pass
        finally: proc.stdin.close()
    readers = [threading.Thread(target=reader, args=(pipe, buf), daemon=True)
               for pipe, buf in zip((proc.stdout, proc.stderr), buffers)]
    for thread in readers: thread.start()
    sender = threading.Thread(target=writer, daemon=True) if data is not None else None
    if sender: sender.start()
    import time
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None or any(thread.is_alive() for thread in readers):
            if overflow.wait(0.01):
                if preview and len(buffers[0]) > limit:
                    return 0, bytes(buffers[0][:limit]) + '\n… 미리보기 한도에 도달했습니다.'.encode(), bytes(buffers[1][:limit])
                raise ValueError('결과가 표시 한도를 초과했습니다.')
            if time.monotonic() >= deadline:
                raise ValueError('응답 시간이 초과되었습니다. 상태를 새로고침해 주세요.')
        if overflow.is_set():
            if preview and len(buffers[0]) > limit:
                return 0, bytes(buffers[0][:limit]) + '\n… 미리보기 한도에 도달했습니다.'.encode(), bytes(buffers[1][:limit])
            raise ValueError('결과가 표시 한도를 초과했습니다.')
        return proc.returncode, bytes(buffers[0]), bytes(buffers[1])
    finally:
        stop(proc)
        for thread in readers: thread.join(timeout=1)
        if sender: sender.join(timeout=1)
        proc.stdout.close(); proc.stderr.close()
