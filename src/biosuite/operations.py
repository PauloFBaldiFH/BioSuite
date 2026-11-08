"""Execução com saída persistente e sem prompts interativos."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import subprocess
import time


class OperationError(Exception):
    pass


def require_root():
    if os.geteuid() != 0:
        raise OperationError('Esta ação exige administrador. Abra com sudo biosuite-config.')


@contextmanager
def lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OperationError('Outra operação BioSuite já está em andamento.') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run_logged(command: list[str], log: Path, output=print, *, env=None, cwd=None):
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with log.open('a') as sink:
        os.chmod(log, 0o600)
        offset = sink.tell()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=sink,
                                   stderr=subprocess.STDOUT, start_new_session=True, env=env, cwd=cwd)
        with log.open() as stream:
            stream.seek(offset)
            while True:
                line = stream.readline()
                if line:
                    output(line.rstrip('\n'))
                elif process.poll() is not None:
                    break
                else:
                    time.sleep(0.1)
        code = process.wait()
    if code:
        raise OperationError(f'Operação terminou com código {code}. Consulte o log: {log}')


def capture(command: list[str], *, timeout=60, cwd=None) -> str:
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=timeout, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired):
        raise OperationError('Não foi possível executar a consulta. Confira pré-requisitos e conectividade.') from None
    if result.returncode:
        raise OperationError(f'Consulta falhou com código {result.returncode}. Verifique o serviço e as permissões.')
    return result.stdout
