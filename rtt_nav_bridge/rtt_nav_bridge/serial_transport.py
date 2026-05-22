from __future__ import annotations

import errno
import os
import select
import termios
import tty


_BAUD_RATES = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
    230400: getattr(termios, 'B230400', termios.B115200),
    460800: getattr(termios, 'B460800', termios.B115200),
    921600: getattr(termios, 'B921600', termios.B115200),
}


class SerialTransport:
    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.fd: int | None = None
        self._rx = bytearray()

    @property
    def is_open(self) -> bool:
        return self.fd is not None

    def open(self) -> None:
        if self.fd is not None:
            return
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            tty.setraw(fd)
            attrs = termios.tcgetattr(fd)
            baud = _BAUD_RATES.get(self.baudrate)
            if baud is None:
                raise ValueError(f'unsupported baudrate: {self.baudrate}')
            attrs[4] = baud
            attrs[5] = baud
            attrs[2] |= termios.CLOCAL | termios.CREAD
            attrs[2] &= ~termios.CRTSCTS
            attrs[3] = 0
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            termios.tcflush(fd, termios.TCIOFLUSH)
        except Exception:
            os.close(fd)
            raise
        self.fd = fd

    def close(self) -> None:
        if self.fd is None:
            return
        fd = self.fd
        self.fd = None
        try:
            os.close(fd)
        except OSError:
            pass

    def read_lines(self, max_bytes: int = 4096) -> list[str]:
        if self.fd is None:
            return []
        lines: list[str] = []
        try:
            ready, _, _ = select.select([self.fd], [], [], 0.0)
            if ready:
                chunk = os.read(self.fd, max_bytes)
                if not chunk:
                    raise OSError(errno.EIO, 'serial device returned EOF')
                self._rx.extend(chunk)
        except BlockingIOError:
            return []
        except OSError:
            self.close()
            raise
        while b'\n' in self._rx:
            raw, _, rest = self._rx.partition(b'\n')
            self._rx = bytearray(rest)
            lines.append(raw.decode('utf-8', errors='replace').strip())
        if len(self._rx) > max_bytes * 2:
            del self._rx[:-max_bytes]
        return lines

    def read_bytes(self, max_bytes: int = 4096) -> bytes:
        if self.fd is None:
            return b''
        try:
            ready, _, _ = select.select([self.fd], [], [], 0.0)
            if not ready:
                return b''
            chunk = os.read(self.fd, max_bytes)
            if not chunk:
                raise OSError(errno.EIO, 'serial device returned EOF')
            return chunk
        except BlockingIOError:
            return b''
        except OSError:
            self.close()
            raise

    def write_bytes(self, data: bytes) -> None:
        if self.fd is None:
            raise OSError(errno.ENOTCONN, 'serial port is not open')
        os.write(self.fd, data)

    def write_line(self, line: str) -> None:
        self.write_bytes(line.encode('utf-8'))
