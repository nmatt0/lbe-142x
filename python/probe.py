#!/usr/bin/env python3
"""
Probe tool for Leo Bodnar LBE-142x family HID devices.
Uses /dev/hidrawN directly — no hidapi dep.

Report size: 60 bytes (feature report), matches HID descriptor on PID 0x2211.
"""
import argparse
import array
import fcntl
import os
import sys
import time

REPORT_SIZE = 60

HIDIOCGFEATURE = lambda n: (3 << 30) | (ord('H') << 8) | (0x07) | (n << 16)
HIDIOCSFEATURE = lambda n: (3 << 30) | (ord('H') << 8) | (0x06) | (n << 16)

OPCODES = {
    "1421_EN_OUT": 0x01, "1421_BLINK": 0x02,
    "1420_SET_F1T": 0x03, "1420_SET_F1": 0x04,
    "1421_SET_F1T": 0x05, "1421_SET_F1": 0x06,
    "1420_SET_PWR1": 0x07,
    "1421_SET_F2T": 0x09, "1421_SET_F2": 0x0A,
    "SET_PLL": 0x0B, "1421_SET_PPS": 0x0C,
    "1421_SET_PWR1": 0x0D, "1421_SET_PWR2": 0x0E,
    "STATUS": 0x4B,
}

def get_feature(fd, report_id=0x4B):
    buf = array.array("B", [report_id] + [0] * (REPORT_SIZE - 1))
    fcntl.ioctl(fd, HIDIOCGFEATURE(REPORT_SIZE), buf, True)
    return bytes(buf)

def set_feature(fd, payload):
    assert len(payload) <= REPORT_SIZE
    buf = array.array("B", list(payload) + [0] * (REPORT_SIZE - len(payload)))
    fcntl.ioctl(fd, HIDIOCSFEATURE(REPORT_SIZE), buf, True)

def refresh_status(fd):
    """DO NOT USE on the Mini: sending opcode 0x0A, 0x04 switches the
    firmware into a mode that returns the HID report descriptor on the
    next GetFeature. Kept for reference; callers should pass
    do_refresh=False."""
    frame = [0] * REPORT_SIZE
    frame[0] = 0x0A
    frame[1] = 0x04
    try:
        set_feature(fd, frame)
    except OSError:
        pass

def snapshot(fd, do_refresh=False):
    if do_refresh:
        refresh_status(fd)
        time.sleep(0.05)
    return get_feature(fd)

def hexdump(data, prefix=""):
    lines = []
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        hex_part = " ".join(f"{b:02X}" for b in row)
        lines.append(f"{prefix}{i:02x}: {hex_part}")
    return "\n".join(lines)

def diff(a, b):
    changes = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            changes.append((i, a[i], b[i]))
    return changes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="/dev/hidraw10")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_dump = sub.add_parser("dump", help="read and pretty-print status report")
    p_dump.add_argument("--refresh", action="store_true",
                        help="send opcode 0x0A,0x04 first (DANGEROUS — on Mini "
                             "this returns HID descriptor instead of status)")
    p_send = sub.add_parser("send", help="send arbitrary feature report and diff status")
    p_send.add_argument("opcode", help="hex byte, e.g. 0x05")
    p_send.add_argument("payload", nargs="*", help="additional hex bytes")
    p_send.add_argument("--at", type=int, default=1,
                        help="byte offset where payload begins (default 1, right after opcode)")
    p_send.add_argument("--no-status-after", action="store_true")
    p_send.add_argument("--settle", type=float, default=0.3,
                        help="seconds between write and re-read (default 0.3)")
    p_freq = sub.add_parser("freq-probe", help="try all known freq-set opcodes at target Hz and diff")
    p_freq.add_argument("hz", type=lambda s: int(s, 0))
    p_sweep = sub.add_parser("sweep", help="probe opcodes in a range; record every status byte that differs")
    p_sweep.add_argument("--lo", type=lambda s: int(s, 0), default=0x00)
    p_sweep.add_argument("--hi", type=lambda s: int(s, 0), default=0x20)
    p_sweep.add_argument("--skip", type=lambda s: int(s, 0), nargs="*", default=[0x06, 0x09],
                         help="opcodes to skip (0x06 causes USB reset on Mini)")
    p_sweep.add_argument("--arg", type=lambda s: int(s, 0), default=0x00,
                         help="single byte argument placed at buf[1] (default 0)")
    args = ap.parse_args()

    fd = os.open(args.dev, os.O_RDWR)
    try:
        if args.cmd == "dump":
            rpt = snapshot(fd, do_refresh=args.refresh)
            print(hexdump(rpt))
            print()
            print(f"byte[1] status = 0x{rpt[1]:02X}")
            for bit in range(8):
                print(f"  bit {bit} = {(rpt[1] >> bit) & 1}")
            freq = rpt[2] | (rpt[3] << 8) | (rpt[4] << 16) | (rpt[5] << 24)
            print(f"freq[2..5] = {freq} Hz")
        elif args.cmd == "send":
            opcode = int(args.opcode, 16)
            payload_bytes = [int(x, 16) for x in args.payload]
            before = snapshot(fd)
            frame = [0] * REPORT_SIZE
            frame[0] = opcode
            for i, b in enumerate(payload_bytes):
                frame[args.at + i] = b
            print(f"send  op=0x{opcode:02X} payload@{args.at}={[f'{b:02X}' for b in payload_bytes]}")
            try:
                set_feature(fd, frame)
            except OSError as e:
                print(f"  ioctl error: {e}")
                return
            if not args.no_status_after:
                time.sleep(args.settle)
                after = snapshot(fd)
                changes = diff(before, after)
                if not changes:
                    print("  no status bytes changed")
                else:
                    for off, a, b in changes:
                        print(f"  [{off:02x}] {a:02X} -> {b:02X}")
        elif args.cmd == "sweep":
            skip = set(args.skip)
            for op in range(args.lo, args.hi + 1):
                if op in skip:
                    print(f"--- op=0x{op:02X} : SKIPPED ---")
                    continue
                before = snapshot(fd)
                frame = [0] * REPORT_SIZE
                frame[0] = op
                frame[1] = args.arg
                try:
                    set_feature(fd, frame)
                except OSError as e:
                    print(f"--- op=0x{op:02X} : ioctl err {e} — device may be gone ---")
                    return
                time.sleep(0.15)
                after = snapshot(fd)
                changes = diff(before, after)
                if changes:
                    diff_str = " ".join(f"[{o:02x}]{a:02X}->{b:02X}" for o, a, b in changes)
                    print(f"op=0x{op:02X} arg=0x{args.arg:02X}: {diff_str}")
                else:
                    print(f"op=0x{op:02X} arg=0x{args.arg:02X}: no change")
        elif args.cmd == "freq-probe":
            hz = args.hz
            fb = [(hz >> 0) & 0xFF, (hz >> 8) & 0xFF, (hz >> 16) & 0xFF, (hz >> 24) & 0xFF]
            # candidates: (opcode label, opcode, payload-offset)
            candidates = [
                ("1420 temp (op=0x03, off=1)", 0x03, 1),
                ("1420 flash (op=0x04, off=1)", 0x04, 1),
                ("1421 temp (op=0x05, off=5)", 0x05, 5),
                ("1421 flash (op=0x06, off=5)", 0x06, 5),
            ]
            for label, op, off in candidates:
                print(f"--- {label} : setting {hz} Hz ---")
                before = get_feature(fd)
                frame = [0] * REPORT_SIZE
                frame[0] = op
                for i, b in enumerate(fb):
                    frame[off + i] = b
                try:
                    set_feature(fd, frame)
                except OSError as e:
                    print(f"  ioctl error: {e}")
                    continue
                time.sleep(0.3)
                after = get_feature(fd)
                changes = diff(before, after)
                if not changes:
                    print("  no status bytes changed")
                else:
                    for off_c, a, b in changes:
                        print(f"  [{off_c:02x}] {a:02X} -> {b:02X}")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
