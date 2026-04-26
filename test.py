#!/usr/bin/env python3
"""Curses TUI for the rpcs3 BNGRW card-reader bridge.

Top pane: scrolling event log (lines from rpcs3).
Status bar: connection state + last reported card state.
Bottom pane: command input.

Bridge protocol (line-based, both directions):

  Stage-then-present (use this from wrapper scripts):
    begin felica <idm_hex>  [pmm_hex]  [sys_hex]
    begin mifare <uid_hex>
    block  <id_hex> <32 hex chars>     # repeat for each block
    present                            # commits staged card
    cancel                             # discards staged card

  One-shot helpers / control:
    none | clear | off | remove        # remove current card
    status | ?                         # request state

  Events from rpcs3:
    state ...                          # current card state
    event select|deselect|release|felica|hello
    event mifare auth/read ...
    event felica_read  block=0xNNNN data=...
    event felica_write block=0xNNNN data=...
    ok ... | err ...
"""

import argparse
import collections
import curses
import socket
import threading
import time
from typing import Deque

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7766
HISTORY = 1000


class Bridge:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.connected = False
        self.last_state = "(unknown)"
        self.led: int | None = None
        self.buzzer: int | None = None
        self.rf_on: bool | None = None
        self.events: Deque[tuple[float, str]] = collections.deque(maxlen=HISTORY)
        self.lock = threading.Lock()

    def add_event(self, line: str) -> None:
        with self.lock:
            self.events.append((time.time(), line))
            if line.startswith("state "):
                self.last_state = line[len("state ") :]
            elif line.startswith("event led "):
                try:
                    self.led = int(line.split()[-1], 16)
                except ValueError:
                    pass
            elif line.startswith("event beep "):
                try:
                    self.buzzer = int(line.split()[-1], 16)
                except ValueError:
                    pass
            elif line == "event rf on":
                self.rf_on = True
            elif line == "event rf off":
                self.rf_on = False

    def connect_loop(self) -> None:
        backoff = 0.5
        while True:
            try:
                s = socket.create_connection((self.host, self.port), timeout=2)
            except OSError as e:
                self.add_event(f"[connect failed: {e}; retry in {backoff:.1f}s]")
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 5.0)
                continue

            s.settimeout(None)
            self.sock = s
            self.connected = True
            backoff = 0.5
            self.add_event(f"[connected {self.host}:{self.port}]")
            try:
                s.sendall(b"status\n")
            except OSError:
                pass

            buf = b""
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        text = line.decode("utf-8", "replace").rstrip()
                        if text:
                            self.add_event(text)
            except OSError as e:
                self.add_event(f"[recv error: {e}]")

            self.connected = False
            self.sock = None
            self.add_event("[disconnected]")
            try:
                s.close()
            except OSError:
                pass
            time.sleep(0.5)

    def send(self, line: str) -> bool:
        s = self.sock
        if s is None:
            return False
        try:
            s.sendall((line + "\n").encode("utf-8"))
            return True
        except OSError as e:
            self.add_event(f"[send failed: {e}]")
            return False


def draw(stdscr, bridge: Bridge, input_buf: list, history: list, hist_idx: list) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 20:
        try:
            stdscr.addstr(0, 0, "window too small")
            stdscr.refresh()
        except curses.error:
            pass
        return

    log_h = h - 3

    with bridge.lock:
        events = list(bridge.events)
        state = bridge.last_state
        connected = bridge.connected
        led = bridge.led
        buzzer = bridge.buzzer
        rf_on = bridge.rf_on

    left = f" rpcs3 BNGRW bridge  {bridge.host}:{bridge.port} "

    def cell(label: str, value: object, on: bool) -> str:
        mark = "[X]" if on else "[ ]"
        return f"{mark} {label}:{value}"

    # LED: bit 0x10 clear = on (0x0b on, 0x1b off observed)
    led_on = (led is not None) and ((led & 0x10) == 0)
    # Buzzer: 0x80 = idle/off, anything else = playing (0x93 observed)
    buz_on = (buzzer is not None) and (buzzer != 0x80)
    rf_state = "ON" if rf_on else ("OFF" if rf_on is False else "?")

    led_txt = cell("LED", f"0x{led:02x}" if led is not None else "--", led_on)
    buz_txt = cell("BUZ", f"0x{buzzer:02x}" if buzzer is not None else "--", buz_on)
    rf_txt = cell("RF", rf_state, bool(rf_on))

    right = f"  {led_txt}  {buz_txt}  {rf_txt} "

    title = left + " " * max(0, w - len(left) - len(right)) + right
    try:
        stdscr.addstr(0, 0, title[:w], curses.A_REVERSE)
    except curses.error:
        pass

    visible = events[-log_h:]
    for i, (ts, line) in enumerate(visible):
        stamp = time.strftime("%H:%M:%S", time.localtime(ts))
        out = f"{stamp}  {line}"
        try:
            stdscr.addstr(1 + i, 0, out[: w - 1])
        except curses.error:
            pass

    status_y = h - 2
    conn_str = "CONNECTED" if connected else "DISCONNECTED"
    status = f" {conn_str}  card: {state} "
    try:
        stdscr.addstr(status_y, 0, status.ljust(w)[:w], curses.A_REVERSE)
    except curses.error:
        pass

    prompt = "> "
    text = "".join(input_buf)
    line = (prompt + text)[: w - 1]
    try:
        stdscr.addstr(h - 1, 0, line)
        stdscr.move(h - 1, min(len(prompt) + len(text), w - 1))
    except curses.error:
        pass

    stdscr.refresh()


def tui(stdscr, bridge: Bridge) -> None:
    curses.curs_set(1)
    stdscr.nodelay(True)
    stdscr.timeout(100)

    input_buf: list[str] = []
    history: list[str] = []
    hist_idx: list[int] = [0]  # boxed

    while True:
        draw(stdscr, bridge, input_buf, history, hist_idx)

        try:
            ch = stdscr.get_wch()
        except curses.error:
            continue
        except KeyboardInterrupt:
            return

        if isinstance(ch, str):
            if ch in ("\n", "\r"):
                line = "".join(input_buf).strip()
                input_buf.clear()
                hist_idx[0] = len(history)
                if not line:
                    continue
                if line in ("quit", "exit"):
                    return
                history.append(line)
                hist_idx[0] = len(history)
                if not bridge.send(line):
                    bridge.add_event(f"[not sent (offline): {line}]")
            elif ch in ("\x7f", "\b"):
                if input_buf:
                    input_buf.pop()
            elif ch == "\x15":  # ctrl-u
                input_buf.clear()
            elif ch == "\x03":  # ctrl-c
                return
            elif ch.isprintable():
                input_buf.append(ch)
        else:
            if ch == curses.KEY_BACKSPACE:
                if input_buf:
                    input_buf.pop()
            elif ch == curses.KEY_UP:
                if history and hist_idx[0] > 0:
                    hist_idx[0] -= 1
                    input_buf.clear()
                    input_buf.extend(history[hist_idx[0]])
            elif ch == curses.KEY_DOWN:
                if hist_idx[0] < len(history) - 1:
                    hist_idx[0] += 1
                    input_buf.clear()
                    input_buf.extend(history[hist_idx[0]])
                else:
                    hist_idx[0] = len(history)
                    input_buf.clear()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    bridge = Bridge(args.host, args.port)
    threading.Thread(target=bridge.connect_loop, daemon=True).start()
    curses.wrapper(tui, bridge)


if __name__ == "__main__":
    main()
