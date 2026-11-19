"""Bounded short-process collector; host scheduling time is never a hardware metric."""
import os
import signal
import subprocess
import time


def execute_counter(command, log_path, timeout, heartbeat):
    if not 0 < timeout <= 1800: raise ValueError('bounded short process timeout required')
    child=None;begin=time.monotonic();previous=signal.getsignal(signal.SIGTERM)
    def interrupted(signum,frame): raise InterruptedError('counter collection stopped')
    signal.signal(signal.SIGTERM,interrupted)
    try:
        with log_path.open('x') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            heartbeat('RTLSIM');next_heartbeat=begin+10
            while child.poll() is None:
                now=time.monotonic()
                if now-begin>timeout:raise subprocess.TimeoutExpired(command,timeout)
                if now>=next_heartbeat:heartbeat('RTLSIM');next_heartbeat=now+10
                time.sleep(min(.05,timeout))
        return child.returncode
    finally:
        if child and child.poll() is None:
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:pass
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait(timeout=5)
        signal.signal(signal.SIGTERM,previous)
