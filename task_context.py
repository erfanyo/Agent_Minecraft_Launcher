"""Cooperative cancellation shared by nested installers and download workers."""
from contextvars import ContextVar, copy_context
import subprocess
import time

cancel_event = ContextVar('cancel_event', default=None)

class TaskCancelled(BaseException):
    """Control flow: must not be swallowed by network fallback handlers."""

def checkpoint():
    event = cancel_event.get()
    if event is not None and event.is_set():
        raise TaskCancelled()

def submit(pool, fn, *args):
    return pool.submit(copy_context().run, fn, *args)

def run_process(command, *, timeout, capture_output=True, **kwargs):
    checkpoint()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    started = time.monotonic()
    try:
        while True:
            checkpoint()
            if time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        process.kill()
        process.communicate()
        raise
