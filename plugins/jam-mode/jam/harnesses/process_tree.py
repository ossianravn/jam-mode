"""Own an episode's process tree, including descendants that outlive the leader."""
from __future__ import annotations

import os
import signal
import subprocess


def launch(command: list[str], **kwargs) -> subprocess.Popen:
    if os.name != "nt":
        return subprocess.Popen(command, start_new_session=True, **kwargs)
    from .windows_job import WindowsJob
    job = WindowsJob()
    process = None
    try:
        process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW | 4, **kwargs)
        job.attach_and_resume(process)
        process.jam_job = job
        return process
    except BaseException:
        job.close()
        if process is not None:
            process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        raise


def stop(process: subprocess.Popen) -> None:
    if os.name == "nt":
        process.jam_job.close()
    else:
        # The session leader may already have exited while children retain pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)
