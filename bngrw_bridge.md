# BNGRW Card Reader Bridge

Virtual Bandai-Namco card reader (BNGRW / "Banapass" / aic_pico-compatible)
emulated inside the rpcs3 USIO USB device, plus a TCP bridge that lets a
host-side script drive the virtual reader.

The bridge exists so that any real NFC reader (libnfc, nfcpy, an aic_pico,
an RC-S380, a PN532 dev board, ...) can be wrapped by a small script that
reads a real card and pushes its contents into rpcs3 over a localhost TCP
socket. rpcs3 itself stays oblivious to which reader is on the other end.

## Architecture

```
+-----------------+      USB transfers       +--------------------+
|  PS3 game       | <--------------------->  |  rpcs3             |
|  (Taiko, etc.)  |                          |  usb_device_usio   |
+-----------------+                          |  (BNGRW emulator)  |
                                             +---------+----------+
                                                       |
                                       TCP 127.0.0.1:7766
                                       (newline-delimited text)
                                                       |
                                             +---------v----------+
                                             |  Wrapper script    |
                                             |  - test.py (TUI)   |
                                             |  - libnfc bridge   |
                                             |  - aic_pico bridge |
                                             +---------+----------+
                                                       |
                                                  Real card
```

The PN532 command emulation in
[`rpcs3/Emu/Io/usio.cpp`](../rpcs3/Emu/Io/usio.cpp) is ported from
aic_pico's `firmware/src/lib/bana.c`. Inside rpcs3 it sits behind the same
USIO USB endpoint Taiko expects.

## Files

| Path | Purpose |
| --- | --- |
| `rpcs3/Emu/Io/usio.cpp` / `usio.h` | USIO emulator + BNGRW PN532 emulation + TCP bridge |
| `test.py` | Curses TUI client for the bridge (interactive testing) |

## TCP bridge

* Listens on `127.0.0.1:7766` from rpcs3 startup.
* Single connected client at a time.
* Newline-delimited UTF-8 text, both directions.
* Non-blocking; bridge poll happens inside the USB poll path, no extra thread.
* Reconnect-safe: server keeps listening; clients can reconnect at any time.

### Commands (host -> rpcs3)

Stage-then-present flow (preferred for wrapper scripts; race-free):

| Command | Effect |
| --- | --- |
| `begin felica <idm_hex> [pmm_hex] [sys_hex]` | Stage a FeliCa card. `idm` is 8 bytes, `pmm` 8 bytes (default `00 f1 00 00 00 01 43 00`), `sys` 2 bytes (default `88 b4`). |
| `begin mifare <uid_hex>` | Stage a Mifare Classic card. `uid` is 4 bytes. |
| `block <id_hex> <32 hex chars>` | Stage one 16-byte block at the given block id. Repeat as needed. Requires a prior `begin`. |
| `present` (alias `commit`) | Atomically swap the staged card into the live state. The game starts seeing the card on its next poll. |
| `cancel` (alias `abort`) | Discard the staged card without presenting. |

One-shot helpers / control:

| Command | Effect |
| --- | --- |
| `none` / `clear` / `off` / `remove` | Remove the current card and any pending stage. |
| `status` / `?` | Ask rpcs3 to emit a `state ...` line. |

Hex parsing accepts spaces, `:`, `-`, and `_` as separators between bytes.

### Events (rpcs3 -> host)

| Event | Meaning |
| --- | --- |
| `event hello` | Sent once when a client connects. |
| `state none` | No card present. |
| `state mifare <uid>` | Mifare card present. |
| `state felica <idm> <pmm> <sys>` | FeliCa card present. |
| `event select` | Game issued PN532 InListPassiveTarget select (0x54). |
| `event deselect` | Game issued InDeselect (0x44). |
| `event release` | Game issued InRelease (0x52). |
| `event mifare auth key=A\|B block=N` | Mifare authenticate (0x60/0x61). |
| `event mifare read block=N` | Mifare read block (0x30). |
| `event felica` | Game issued raw FeliCa command (0xa0). |
| `event felica_read block=0xNNNN data=...` | FeliCa Read Without Encryption (cmd 0x06) for one block. |
| `event felica_write block=0xNNNN data=...` | FeliCa Write Without Encryption (cmd 0x08) for one block. |
| `event felica unhandled cmd=0xNN` | FeliCa subcommand other than 0x06/0x08; not implemented. |
| `event led 0xNN` | PN532 WriteGPIO with port 0x01 (reader LED). |
| `event beep 0xNN` | PN532 WriteGPIO with port 0x08 (buzzer). |
| `event gpio port=0xNN value=0xNN` | Other GPIO writes. |
| `event rf on` / `event rf off` | RF field toggle (PN532 RFConfiguration 0x32). |
| `ok ...` | Acknowledgement of a host command. |
| `err <reason>` | Command rejected (e.g. `err block bad_hex`, `err present no_pending`). |

#### Observed control byte mappings

(LED + buzzer values are not part of the PN532 spec; they are reader-side
firmware codes, observed empirically against the Taiko hardware-test menu.)

| Subsystem | Idle / off | Active / on |
| --- | --- | --- |
| Reader LED | `0x1b` | `0x0b` (bit `0x10` clear = on) |
| Buzzer | `0x80` | anything else (`0x93` observed during beep) |

The TUI uses these mappings to drive its status checkboxes.

### Example session

A wrapper script reading a real banapass card might send:

```
begin felica 01 02 03 04 05 06 07 08 00 f1 00 00 00 01 43 00 88 b4
block 0000 33 31 32 33 34 35 36 37 38 39 30 31 32 33 34 35
block 8082 01 02 03 04 05 06 07 08 00 2a 00 00 00 00 00 00
block 8088 11 22 33 44 55 66 77 88 99 aa bb cc dd ee ff 00
present
```

Then rpcs3 emits:

```
ok begin felica
ok block 0x0000
ok block 0x8082
ok block 0x8088
ok present
state felica 01 02 03 04 05 06 07 08 00 F1 00 00 00 01 43 00 88 B4
event rf on
event select
event felica_read block=0x8082 data=01 02 03 04 05 06 07 08 00 2A 00 00 00 00 00 00
event felica_read block=0x0000 data=33 31 32 33 34 35 36 37 38 39 30 31 32 33 34 35
event led 0x0b
event beep 0x93
...
```

To remove the card:

```
clear
```

## FeliCa emulation details

Implemented inside `bngrw_cmd_felica` in `usio.cpp`. PN532 opcode `0xa0`
delivers a FeliCa frame, format:

```
[timeout_lo] [timeout_hi] [felica_len] [felica_cmd] [body...]
```

| `felica_cmd` | Name | Status |
| --- | --- | --- |
| `0x06` | Read Without Encryption | Implemented |
| `0x08` | Write Without Encryption | Implemented |
| anything else | -- | Logged as `event felica unhandled cmd=0xNN`, returns generic OK |

Read response payload (wrapped by `bngrw_send_response` into a PN532 frame):

```
[0x00 status] [len] [0x07 cmd] [idm * 8] [flag1=00] [flag2=00] [block_count]
[block * 16] ...
```

Block descriptors in the request support both 2-byte and 3-byte forms
(distinguished by the high bit of the first byte). Only the block index
is honoured; service codes are accepted but ignored. Block storage lives
on `bngrw_card_state::blocks` as a `std::map<u16, std::array<u8, 16>>`.
Blocks not previously written read back as zeros.

Write response payload:

```
[0x00 status] [len=0x0c] [0x09 cmd] [idm * 8] [flag1=00] [flag2=00]
```

PN532 InCommunicateThru (`0x42`) is intentionally a stub returning
`{0x01}`, matching aic_pico. Real Taiko games drive FeliCa via the `0xa0`
path, not InCommunicateThru.

## TUI client (`test.py`)

`python3 test.py [--host 127.0.0.1] [--port 7766]`

Layout:

```
+--------------------------------------------------------------+
| rpcs3 BNGRW bridge 127.0.0.1:7766   [X] LED:0x0b  [ ] BUZ:.. |  <-- title bar (live)
| 18:20:30  event hello                                         |
| 18:20:31  state none                                          |
| 18:20:32  event rf on                                         |
| ...                                                           |  <-- scrolling event log
|                                                               |
| CONNECTED  card: felica 01 02 ...                             |  <-- status bar
| > begin felica 0123456789abcdef                               |  <-- input
+--------------------------------------------------------------+
```

* Title bar shows the bridge address plus three live indicators:
  `LED`, `BUZ`, `RF`. Each has `[X]` / `[ ]` plus the raw hex byte value
  for LED and buzzer. The on/off thresholds use the observed mappings
  documented above.
* Event log: timestamped, newest at the bottom, scrolls. Holds the last
  1000 events.
* Status bar: connection state and the most recent `state ...` line.
* Input line: type a bridge command and press Enter. `quit` / `exit` /
  Ctrl-C exits. Up/Down browse history. Backspace edits. Ctrl-U clears.
* Auto-reconnect: if rpcs3 is restarted, the TUI keeps trying every
  ~0.5-5 s.

## Writing a wrapper for a real reader

Skeleton:

```python
import socket, time

def push_card(sock, idm, blocks: dict[int, bytes]):
    def hx(b): return b.hex()
    sock.sendall(f"begin felica {hx(idm)}\n".encode())
    for bid, data in blocks.items():
        sock.sendall(f"block {bid:04x} {hx(data)}\n".encode())
    sock.sendall(b"present\n")

s = socket.create_connection(("127.0.0.1", 7766))
# ... read real card with libnfc / nfcpy / aic_pico / etc ...
push_card(s, idm_bytes, {0x0000: block0, 0x8082: block82, 0x8088: block88})

# When card is taken away from the real reader:
s.sendall(b"clear\n")
```

Stage-then-present is the right pattern when the underlying read is
streaming (block by block). Block content can keep updating between
`present` calls without ever showing the game a half-loaded card.

## Limitations / TODO

* FeliCa subcommands beyond Read/Write Without Encryption are stubbed.
  Mutual auth (`Authentication1`/`Authentication2`, cmd `0x10`/`0x12`)
  used by FeliCa Lite-S secure mode is not implemented; the bridge
  currently emits `event felica unhandled cmd=0xNN` and returns a
  generic OK, which is enough for plain Read/Write but not for cards
  that gate access on auth.
* No persistence: block writes survive only until the card is cleared
  or rpcs3 exits. Adding a `save_card <path>` / `load_card <path>` pair
  is straightforward.
* Single client: `accept` happens once per poll and only one client is
  tracked. A new connection while one is active will sit in the listen
  backlog until the first disconnects.
* Cross-platform sockets: code uses winsock on Windows and BSD sockets
  on Linux/macOS; `MSG_NOSIGNAL` used on POSIX, plain `send` on Windows.
  Tested on Linux only so far.

## Reference

* aic_pico firmware (source of the BNGRW PN532 emulation):
  `firmware/src/lib/bana.c` and `firmware/src/lib/nfc.c`.
* PN532 user manual (NXP UM0701-02) for opcode definitions.
* FeliCa Lite-S User's Manual (Sony) for block layout and Read/Write
  Without Encryption frame format.
