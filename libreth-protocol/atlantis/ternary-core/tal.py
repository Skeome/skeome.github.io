#!/usr/bin/env python3
"""
Ternary-AL v3.1 — Native Python Interpreter
============================================
Author:  Skeome  (Python port)
ISA Ref: Ternary_AL_v3_1_Reference.md

Implements the full 93-opcode Tesseract ISA directly in Python,
eliminating the Julia middleman entirely.

Usage:
    python tal.py                        # interactive REPL
    python tal.py program.tal            # run a file
    python tal.py program.tal --trace    # run with per-instruction trace
    python tal.py program.tal --step     # single-step with monitor
    python tal.py --no-monitor           # suppress post-run monitor
    python tal.py --receptor usb         # force USB/serial receptor
    python tal.py --receptor sim         # force simulated receptor
    python tal.py --receptor auto        # hardware auto-detect (default)
    python tal.py --list-ports           # list available serial/USB ports
"""

from __future__ import annotations

import sys
import os
import re
import struct
import random
import math
import argparse
import time
import glob
import readline  # enables arrow-key history in REPL (Unix/macOS)
from copy import deepcopy
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from enum import IntEnum

# ─────────────────────────────────────────────────────────────────────────────
# TRIT ENUMERATION
# ─────────────────────────────────────────────────────────────────────────────

class Trit(IntEnum):
    Neg  = -1
    Zero =  0
    Pos  =  1

NEG  = Trit.Neg
ZERO = Trit.Zero
POS  = Trit.Pos

TRIT_SYM = {NEG: 'T', ZERO: '0', POS: '1'}
SYM_TRIT = {'T': NEG, '0': ZERO, '1': POS,
             't': NEG, 'N': NEG, 'n': NEG}

def trit_from_int(n: int) -> Trit:
    if n > 0: return POS
    if n < 0: return NEG
    return ZERO

def trits_to_string(trits: List[Trit]) -> str:
    """MST first (index 0 = LST internally, so reverse)."""
    return ''.join(TRIT_SYM[t] for t in reversed(trits))

# ─────────────────────────────────────────────────────────────────────────────
# KLEENE THREE-VALUED LOGIC GATES
# ─────────────────────────────────────────────────────────────────────────────

def tNOT(t: Trit) -> Trit:  return Trit(-t)
def tAND(a: Trit, b: Trit) -> Trit:  return Trit(min(a, b))
def tOR (a: Trit, b: Trit) -> Trit:  return Trit(max(a, b))
def tNAND(a,b): return tNOT(tAND(a,b))
def tNOR (a,b): return tNOT(tOR (a,b))
def tXOR (a,b): return tOR(tAND(a,tNOT(b)), tAND(tNOT(a),b))
def tXNOR(a,b): return tNOT(tXOR(a,b))
def tIMP (a,b): return tOR(tNOT(a), b)
def tCONS(a,b):
    s = a + b
    if s > 1:  return POS
    if s < -1: return NEG
    return ZERO
def tMAJ(a,b,c):
    s = a + b + c
    if s > 0: return POS
    if s < 0: return NEG
    return ZERO

# ─────────────────────────────────────────────────────────────────────────────
# ARITHMETIC — BigInt via Python's arbitrary-precision int
# ─────────────────────────────────────────────────────────────────────────────

REG_WIDTH  = 81
INSTR_LEN  = 81
N_REGS     = 27          # R0..R26
SP_REG     = 26          # R26 = stack pointer by convention
MAX_REG_VAL = (3**REG_WIDTH - 1) // 3   # ≈ 2.21×10^38

def bt_to_int(trits: List[Trit]) -> int:
    """LST-first list → Python int (arbitrary precision)."""
    return sum(int(t) * (3**i) for i, t in enumerate(trits))

def int_to_bt(n: int, length: int) -> List[Trit]:
    """Python int → LST-first balanced-ternary list of given length."""
    digits = []
    temp = n
    while len(digits) < length:
        r = temp % 3
        if r == 2 or r == -1:
            r = -1; temp = (temp + 1) // 3
        elif r == 1 or r == -2:
            r = 1;  temp = (temp - 1) // 3
        else:
            temp = temp // 3
        digits.append(Trit(r))
        if len(digits) >= length and temp == 0:
            break
    while len(digits) < length:
        digits.append(ZERO)
    return digits[:length]

def sat(n: int) -> List[Trit]:
    """Saturate to register range and encode."""
    return int_to_bt(max(-MAX_REG_VAL, min(MAX_REG_VAL, n)), REG_WIDTH)

def reg_int(v: List[Trit]) -> int:
    return bt_to_int(v)

def sat_add(a: List[Trit], b: List[Trit]) -> List[Trit]:
    return sat(reg_int(a) + reg_int(b))

def tritwise(a: List[Trit], b: List[Trit], gate) -> List[Trit]:
    """Apply binary gate element-wise across REG_WIDTH trits."""
    pa = (a + [ZERO]*REG_WIDTH)[:REG_WIDTH]
    pb = (b + [ZERO]*REG_WIDTH)[:REG_WIDTH]
    return [gate(pa[i], pb[i]) for i in range(REG_WIDTH)]

def tritwise_not(a: List[Trit]) -> List[Trit]:
    return [tNOT(t) for t in a]

def shift_left(w: List[Trit], n: int=1) -> List[Trit]:
    n = max(0, min(n, len(w)))
    return ([ZERO]*n + w)[:len(w)]

def shift_right(w: List[Trit], n: int=1) -> List[Trit]:
    n = max(0, min(n, len(w)))
    return (w + [ZERO]*n)[n:n+len(w)]

def rotate_left(w: List[Trit], n: int=1) -> List[Trit]:
    n = n % max(len(w), 1)
    return w[n:] + w[:n]

def rotate_right(w: List[Trit], n: int=1) -> List[Trit]:
    n = n % max(len(w), 1)
    return w[-n:] + w[:-n]

def abs_reg(a: List[Trit]) -> List[Trit]:
    return sat(abs(reg_int(a)))

def set_status(val: List[Trit]) -> Trit:
    n = reg_int(val)
    if n > 0: return POS
    if n < 0: return NEG
    return ZERO

# ─────────────────────────────────────────────────────────────────────────────
# OPCODE CONSTANTS  (all v2.0 values preserved; v3.1 additions appended)
# ─────────────────────────────────────────────────────────────────────────────

# System Control
OP_HALT    = -9477; OP_RESET  = -9476
OP_PRINT   = -8748; OP_DUMP   = -8747; OP_PRINTS = -8746
OP_PRINTI  = -8745; OP_PRINTB = -8744
# v3.1 Stack & Subroutines
OP_PUSH    = -8019; OP_POP    = -8018; OP_CALL   = -8017; OP_RET    = -8016
OP_INT_EN  = -8015; OP_INT_DIS= -8014; OP_IVEC   = -8013; OP_IRET   = -8012
# Compare & Branch
OP_CMP     = -7290; OP_CMPI   = -7289; OP_MIN    = -7288; OP_MAX    = -7287
OP_JMP     = -6561; OP_JEZ    = -6560; OP_JNZ    = -6559
OP_JGT     = -6558; OP_JLT    = -6557; OP_JGEZ   = -6556; OP_JLEZ   = -6555
# Shift & Rotate
OP_LSHIFT  = -5832; OP_RSHIFT = -5831; OP_LSHIFTN= -5830; OP_RSHIFTN= -5829
OP_ROTL    = -5828; OP_ROTR   = -5827
# Kleene Logic
OP_TNOT    = -5103; OP_TNAND  = -5102; OP_TNOR   = -5101; OP_TXNOR  = -5100
OP_TIMP    = -5099; OP_TMUX   = -5098; OP_TMAJ   = -5097; OP_TCONS  = -5096
OP_TSEL    = -5095  # v3.1
# Arithmetic & Logic
OP_TXOR    = -4374; OP_TXORI  = -4373
OP_TOR     = -3645; OP_TORI   = -3644
OP_TAND    = -2916; OP_TANDI  = -2915
OP_DIV     = -2187; OP_DIVI   = -2186; OP_MOD    = -2185; OP_MODI   = -2184
OP_MUL     = -1458; OP_MULI   = -1457
OP_STORE   = -729;  OP_STORER = -728;  OP_STOREI = -727
OP_STOREX  = -726;  OP_STORERR= -725   # v3.1
OP_NOP     =  0
OP_LOAD    =  729;  OP_LOADI  =  730;  OP_LOADR  =  731
OP_LOADX   =  732;  OP_LOADRR =  733   # v3.1
OP_MOV     =  1458; OP_XCHG   =  1459
OP_ADD     =  2187; OP_ADDI   =  2188
OP_SUB     =  2916; OP_SUBI   =  2917; OP_NEG    =  2918; OP_ABS    =  2919
OP_INC     =  3645; OP_DEC    =  3646; OP_SIGN   =  3647
OP_TGET    =  3648; OP_TSET   =  3649; OP_TSWAP  =  3650  # v3.1
OP_SSET    =  4374
# Hardware Receptor
OP_RECEP   =  5103; OP_SENSE  =  5104; OP_SAMP_DB=  5105
OP_SETTH_P =  5832; OP_SETTH_N=  5833; OP_RCLEAR =  5834; OP_RSTAT  =  5835
OP_QUERY_I2C=6561;  OP_WRITE_I2C=6562
OP_QUERY_SPI=7290;  OP_WRITE_SPI=7291
OP_GPIO_READ=8019;  OP_GPIO_WRITE=8020
OP_NVLOAD  =  8748; OP_NVSTORE=  8749  # v3.1
OP_COHERE  =  9477; OP_ARRAY_N=  9478; OP_GAIN   =  9479

OPCODE_NAMES: Dict[int, str] = {
    OP_HALT:"HALT", OP_RESET:"RESET",
    OP_PRINT:"PRINT", OP_DUMP:"DUMP", OP_PRINTS:"PRINTS",
    OP_PRINTI:"PRINTI", OP_PRINTB:"PRINTB",
    OP_PUSH:"PUSH", OP_POP:"POP", OP_CALL:"CALL", OP_RET:"RET",
    OP_INT_EN:"INT_EN", OP_INT_DIS:"INT_DIS", OP_IVEC:"IVEC", OP_IRET:"IRET",
    OP_CMP:"CMP", OP_CMPI:"CMPI", OP_MIN:"MIN", OP_MAX:"MAX",
    OP_JMP:"JMP", OP_JEZ:"JEZ", OP_JNZ:"JNZ",
    OP_JGT:"JGT", OP_JLT:"JLT", OP_JGEZ:"JGEZ", OP_JLEZ:"JLEZ",
    OP_LSHIFT:"LSHIFT", OP_RSHIFT:"RSHIFT",
    OP_LSHIFTN:"LSHIFTN", OP_RSHIFTN:"RSHIFTN",
    OP_ROTL:"ROTL", OP_ROTR:"ROTR",
    OP_TNOT:"TNOT", OP_TNAND:"TNAND", OP_TNOR:"TNOR", OP_TXNOR:"TXNOR",
    OP_TIMP:"TIMP", OP_TMUX:"TMUX", OP_TMAJ:"TMAJ", OP_TCONS:"TCONS",
    OP_TSEL:"TSEL",
    OP_TXOR:"TXOR", OP_TXORI:"TXORI",
    OP_TOR:"TOR",   OP_TORI:"TORI",
    OP_TAND:"TAND", OP_TANDI:"TANDI",
    OP_DIV:"DIV",   OP_DIVI:"DIVI",   OP_MOD:"MOD",   OP_MODI:"MODI",
    OP_MUL:"MUL",   OP_MULI:"MULI",
    OP_STORE:"STORE", OP_STORER:"STORER", OP_STOREI:"STOREI",
    OP_STOREX:"STOREX", OP_STORERR:"STORERR",
    OP_NOP:"NOP",
    OP_LOAD:"LOAD", OP_LOADI:"LOADI", OP_LOADR:"LOADR",
    OP_LOADX:"LOADX", OP_LOADRR:"LOADRR",
    OP_MOV:"MOV", OP_XCHG:"XCHG",
    OP_ADD:"ADD", OP_ADDI:"ADDI",
    OP_SUB:"SUB", OP_SUBI:"SUBI", OP_NEG:"NEG", OP_ABS:"ABS",
    OP_INC:"INC", OP_DEC:"DEC", OP_SIGN:"SIGN",
    OP_TGET:"TGET", OP_TSET:"TSET", OP_TSWAP:"TSWAP",
    OP_SSET:"SSET",
    OP_RECEP:"RECEP", OP_SENSE:"SENSE", OP_SAMP_DB:"SAMP_DB",
    OP_SETTH_P:"SETTH_P", OP_SETTH_N:"SETTH_N",
    OP_RCLEAR:"RCLEAR", OP_RSTAT:"RSTAT",
    OP_QUERY_I2C:"QUERY_I2C", OP_WRITE_I2C:"WRITE_I2C",
    OP_QUERY_SPI:"QUERY_SPI", OP_WRITE_SPI:"WRITE_SPI",
    OP_GPIO_READ:"GPIO_READ", OP_GPIO_WRITE:"GPIO_WRITE",
    OP_NVLOAD:"NVLOAD", OP_NVSTORE:"NVSTORE",
    OP_COHERE:"COHERE", OP_ARRAY_N:"ARRAY_N", OP_GAIN:"GAIN",
}

# ─────────────────────────────────────────────────────────────────────────────
# INSTRUCTION ENCODE / DECODE
# ─────────────────────────────────────────────────────────────────────────────

def assemble_instr(opcode: int,
                   dst:  int=0, src1: int=0, src2: int=0, src3: int=0,
                   *, lane: int=0, flags: int=0, sub: int=0, imm: int=0
                   ) -> List[Trit]:
    """Encode one 81-trit instruction (27-27-27 layout)."""
    return (
        int_to_bt(opcode,    27) +  # Segment A
        int_to_bt(dst  - 13,  3) +  # Segment B: DST  (R0 → -13, R26 → +13)
        int_to_bt(src1 - 13,  3) +
        int_to_bt(src2 - 13,  3) +
        int_to_bt(src3 - 13,  3) +
        int_to_bt(lane,       3) +
        int_to_bt(flags,      3) +
        int_to_bt(sub,        9) +
        int_to_bt(imm,       27)    # Segment C
    )

def decode_instr(mem: List[Trit], pc: int):
    """Decode 81-trit instruction at pc (1-based). Returns tuple."""
    raw = mem[pc-1 : pc-1+INSTR_LEN]
    raw += [ZERO] * max(0, INSTR_LEN - len(raw))

    opcode = bt_to_int(raw[0:27])

    def ridx(sl): return bt_to_int(sl) + 13   # BT offset +13 → 0..26

    dst   = ridx(raw[27:30])
    src1  = ridx(raw[30:33])
    src2  = ridx(raw[33:36])
    src3  = ridx(raw[36:39])
    lane  = bt_to_int(raw[39:42])
    flags = raw[42:45]
    sub   = bt_to_int(raw[45:54])
    imm   = raw[54:81]

    return opcode, dst, src1, src2, src3, lane, flags, sub, imm

# ─────────────────────────────────────────────────────────────────────────────
# HARDWARE RECEPTOR BACKENDS
# ─────────────────────────────────────────────────────────────────────────────

class ReceptorBackend:
    n_channels: int = 0
    pos_threshold: float = 0.5
    neg_threshold: float = -0.5

    def read_voltages(self) -> List[float]:
        raise NotImplementedError

    def close(self): pass

    def decode_analogue(self, v: float) -> Trit:
        if v > self.pos_threshold: return POS
        if v < self.neg_threshold: return NEG
        return ZERO


class SimulatedBackend(ReceptorBackend):
    """Stochastic-resonance model. No external deps."""
    def __init__(self, n_channels=8, signal_prob=0.1,
                 coherence=0.0, array_n=1, directed=0.6,
                 pos_threshold=0.5, neg_threshold=-0.5):
        self.n_channels      = n_channels
        self.signal_prob     = signal_prob
        self.coherence       = coherence   # ξ
        self.array_n         = array_n     # N
        self.directed        = directed
        self.pos_threshold   = pos_threshold
        self.neg_threshold   = neg_threshold

    def operator_gain(self) -> float:
        return self.coherence**2 * float(self.array_n)**2

    def read_voltages(self) -> List[float]:
        G = self.operator_gain()
        return [
            max(-1.5, min(1.5,
                self.signal_prob * random.gauss(0, 1) +
                self.directed * self.coherence * G * 0.1))
            for _ in range(self.n_channels)
        ]

    def close(self): pass


class USBSerialBackend(ReceptorBackend):
    """
    USB / Serial UART receptor backend.
    Reads comma-separated voltage values from the port.
    Requires: pip install pyserial
    Format expected from device:  V0:1.23,V1:-0.45,V2:0.00,...\\n
      or simply:                  1.23,-0.45,0.00,...\\n
    """
    def __init__(self, port: str, baud: int=115200, n_channels: int=4,
                 pos_threshold=0.5, neg_threshold=-0.5, timeout=0.1):
        try:
            import serial
            self._ser = serial.Serial(port, baud, timeout=timeout)
            time.sleep(0.1)  # allow device to settle
        except ImportError:
            raise RuntimeError(
                "pyserial not installed. Run: pip install pyserial")
        except Exception as e:
            raise RuntimeError(f"Cannot open {port} @ {baud}: {e}")

        self.port            = port
        self.baud            = baud
        self.n_channels      = n_channels
        self.pos_threshold   = pos_threshold
        self.neg_threshold   = neg_threshold
        self._last: List[float] = [0.0] * n_channels
        print(f"[USB] Opened {port} @ {baud} baud, {n_channels} channels")

    def read_voltages(self) -> List[float]:
        try:
            if self._ser.in_waiting:
                raw = self._ser.readline().decode(errors='replace').strip()
                # Strip "Vn:" prefixes, split on comma
                raw = re.sub(r'V\d+:', '', raw)
                vals = []
                for tok in raw.split(','):
                    try: vals.append(float(tok.strip()))
                    except ValueError: pass
                if len(vals) >= self.n_channels:
                    self._last = vals[:self.n_channels]
        except Exception:
            pass
        return list(self._last)

    def write(self, data: bytes):
        """Send raw bytes to the USB device."""
        try: self._ser.write(data)
        except Exception as e:
            print(f"[USB] Write error: {e}")

    def close(self):
        try: self._ser.close()
        except Exception: pass


class ADS1115Backend(ReceptorBackend):
    """I²C ADS1115 16-bit ADC. Requires smbus2."""
    def __init__(self, bus=1, address=0x48, n_channels=4,
                 pos_threshold=0.5, neg_threshold=-0.5):
        try:
            import smbus2
            self._bus = smbus2.SMBus(bus)
        except ImportError:
            raise RuntimeError("smbus2 not installed: pip install smbus2")
        self.address       = address
        self.n_channels    = n_channels
        self.pos_threshold = pos_threshold
        self.neg_threshold = neg_threshold
        print(f"[ADS1115] I²C bus={bus} addr=0x{address:02X} ch={n_channels}")

    MUX = [0b100, 0b101, 0b110, 0b111]
    LSB = 0.125e-3  # 4.096V PGA

    def _read_ch(self, ch: int) -> float:
        mux = self.MUX[max(0, min(ch, 3))]
        cfg_hi = 0x80 | (mux << 4) | (0b001 << 1) | 0x01
        cfg_lo = 0x83
        self._bus.write_i2c_block_data(self.address, 0x01, [cfg_hi, cfg_lo])
        time.sleep(0.01)
        data = self._bus.read_i2c_block_data(self.address, 0x00, 2)
        raw = struct.unpack('>h', bytes(data))[0]
        return raw * self.LSB

    def read_voltages(self) -> List[float]:
        return [self._read_ch(i) for i in range(self.n_channels)]

    def close(self):
        try: self._bus.close()
        except Exception: pass


class MCP3008Backend(ReceptorBackend):
    """SPI MCP3008 10-bit ADC. Requires spidev."""
    def __init__(self, bus=0, device=0, vref=3.3, n_channels=8,
                 pos_threshold=0.5, neg_threshold=-0.5):
        try:
            import spidev
            self._spi = spidev.SpiDev()
            self._spi.open(bus, device)
            self._spi.max_speed_hz = 1_350_000
        except ImportError:
            raise RuntimeError("spidev not installed: pip install spidev")
        self.vref          = vref
        self.n_channels    = n_channels
        self.pos_threshold = pos_threshold
        self.neg_threshold = neg_threshold
        print(f"[MCP3008] SPI bus={bus}.{device} vref={vref}V ch={n_channels}")

    def _read_ch(self, ch: int) -> float:
        tx = [0x01, (0x80 | (ch << 4)), 0x00]
        rx = self._spi.xfer2(tx)
        raw = ((rx[1] & 0x03) << 8) | rx[2]
        return (raw / 1023.0) * self.vref - self.vref / 2.0

    def read_voltages(self) -> List[float]:
        return [self._read_ch(i) for i in range(self.n_channels)]

    def close(self):
        try: self._spi.close()
        except Exception: pass


class GPIOBackend(ReceptorBackend):
    """RPi GPIO digital threshold backend. Requires RPi.GPIO or gpiod."""
    def __init__(self, pin_pairs: List[Tuple[int,int]],
                 pos_threshold=0.5, neg_threshold=-0.5):
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            for pp, pn in pin_pairs:
                GPIO.setup(pp, GPIO.IN)
                GPIO.setup(pn, GPIO.IN)
        except ImportError:
            raise RuntimeError("RPi.GPIO not available on this platform")
        self.pin_pairs     = pin_pairs
        self.n_channels    = len(pin_pairs)
        self.pos_threshold = pos_threshold
        self.neg_threshold = neg_threshold
        print(f"[GPIO] {self.n_channels} differential channels")

    def read_voltages(self) -> List[float]:
        result = []
        for pp, pn in self.pin_pairs:
            hi = self._gpio.input(pp)
            lo = self._gpio.input(pn)
            v = 1.0 if (hi and not lo) else (-1.0 if (lo and not hi) else 0.0)
            result.append(v)
        return result

    def close(self):
        try: self._gpio.cleanup()
        except Exception: pass


def list_serial_ports() -> List[str]:
    """Return list of available serial/USB port names."""
    ports = []
    if sys.platform.startswith('win'):
        for i in range(256):
            try:
                import serial
                s = serial.Serial(f'COM{i}')
                s.close()
                ports.append(f'COM{i}')
            except Exception: pass
    else:
        ports += glob.glob('/dev/ttyUSB*')
        ports += glob.glob('/dev/ttyACM*')
        ports += glob.glob('/dev/ttyS*')
        ports += glob.glob('/dev/cu.usb*')
        ports += glob.glob('/dev/cu.serial*')
    return sorted(ports)


def detect_hardware(n_channels=4, force_usb_port=None,
                    pos_threshold=0.5, neg_threshold=-0.5,
                    verbose=True) -> ReceptorBackend:
    """
    Auto-detection order:
      USB/Serial (if --receptor usb or port found)
      → ADS1115 (I²C)
      → MCP3008 (SPI)
      → GPIO (RPi)
      → Simulated
    """
    if force_usb_port:
        try:
            return USBSerialBackend(force_usb_port, n_channels=n_channels,
                                    pos_threshold=pos_threshold,
                                    neg_threshold=neg_threshold)
        except Exception as e:
            if verbose: print(f"[Hardware] USB/Serial failed: {e}")

    # Auto-probe USB/Serial ports
    for port in list_serial_ports():
        try:
            b = USBSerialBackend(port, n_channels=n_channels,
                                 pos_threshold=pos_threshold,
                                 neg_threshold=neg_threshold)
            if verbose: print(f"[Hardware] USB/Serial found on {port}")
            return b
        except Exception as e:
            if verbose: print(f"[Hardware] {port}: {e}")

    # I²C ADS1115
    if os.path.exists('/dev/i2c-1'):
        try:
            return ADS1115Backend(n_channels=min(n_channels,4),
                                  pos_threshold=pos_threshold,
                                  neg_threshold=neg_threshold)
        except Exception as e:
            if verbose: print(f"[Hardware] ADS1115 unavailable: {e}")

    # SPI MCP3008
    if os.path.exists('/dev/spidev0.0'):
        try:
            return MCP3008Backend(n_channels=min(n_channels,8),
                                  pos_threshold=pos_threshold,
                                  neg_threshold=neg_threshold)
        except Exception as e:
            if verbose: print(f"[Hardware] MCP3008 unavailable: {e}")

    # GPIO
    if os.path.exists('/dev/gpiochip0') or os.path.exists('/dev/gpiochip4'):
        try:
            return GPIOBackend([], pos_threshold=pos_threshold,
                               neg_threshold=neg_threshold)
        except Exception as e:
            if verbose: print(f"[Hardware] GPIO unavailable: {e}")

    if verbose: print("[Hardware] SimulatedBackend active (stochastic resonance)")
    return SimulatedBackend(n_channels=n_channels,
                            pos_threshold=pos_threshold,
                            neg_threshold=neg_threshold)


# ─────────────────────────────────────────────────────────────────────────────
# RECEPTOR INTERFACE  (wraps backend with history/majority-vote)
# ─────────────────────────────────────────────────────────────────────────────

class ReceptorInterface:
    def __init__(self, backend: ReceptorBackend, history_depth=100):
        self.backend      = backend
        self.history: List[List[Trit]] = []
        self.history_depth = history_depth
        self.sample_count  = 0
        self.pos_threshold = backend.pos_threshold
        self.neg_threshold = backend.neg_threshold
        self._last_states: List[Trit] = [ZERO] * backend.n_channels

    def sample(self) -> List[Trit]:
        voltages = self.backend.read_voltages()
        states = [self.backend.decode_analogue(v) for v in voltages]
        # Force length == n_channels
        while len(states) < self.backend.n_channels:
            states.append(ZERO)
        self._last_states = states[:self.backend.n_channels]
        self.history.append(list(self._last_states))
        if len(self.history) > self.history_depth:
            self.history.pop(0)
        self.sample_count += 1
        return self._last_states

    def majority_vote(self, n=10) -> List[Trit]:
        n = min(n, len(self.history))
        if n == 0:
            return [ZERO] * self.backend.n_channels
        result = []
        for ch in range(self.backend.n_channels):
            counts = {NEG: 0, ZERO: 0, POS: 0}
            for snap in self.history[-n:]:
                if ch < len(snap):
                    counts[snap[ch]] += 1
            result.append(max(counts, key=counts.get))
        return result

    def show_status(self):
        print("\n── RECEPTOR LAYER ─────────────────────────────────────────────────")
        print(f"Backend  : {type(self.backend).__name__}")
        print(f"Channels : {self.backend.n_channels}   Samples: {self.sample_count}")
        if isinstance(self.backend, SimulatedBackend):
            b = self.backend
            print(f"Coherence: ξ={b.coherence:.3f}  N={b.array_n}  "
                  f"Gain={b.operator_gain():.2e}")
        elif isinstance(self.backend, USBSerialBackend):
            print(f"Port     : {self.backend.port} @ {self.backend.baud} baud")
        print(f"{'CH':<4} {'State':<7} {'Voltage':>10}  Threshold ±")
        print("─────────────────────────────────────────────────────────────────")
        voltages = self.backend.read_voltages()
        for i, t in enumerate(self._last_states):
            v = voltages[i] if i < len(voltages) else 0.0
            print(f" {i:<3d}   {TRIT_SYM[t]:<7}  {v:+9.4f} V")
        if len(self.history) >= 3:
            mv = self.majority_vote(min(10, len(self.history)))
            print(f"Majority vote (last {min(10,len(self.history))}): "
                  f"{''.join(TRIT_SYM[t] for t in mv)}")
        print("─────────────────────────────────────────────────────────────────")


# ─────────────────────────────────────────────────────────────────────────────
# NON-VOLATILE STORE
# ─────────────────────────────────────────────────────────────────────────────

NV_FILE = "nv_store.bin"
_nv_store: Dict[int, List[Trit]] = {}

def nv_load(key: int) -> List[Trit]:
    return list(_nv_store.get(key, [ZERO]*REG_WIDTH))

def nv_store(key: int, val: List[Trit]):
    _nv_store[key] = list(val)
    try:
        with open(NV_FILE, 'wb') as f:
            for k, v in _nv_store.items():
                f.write(struct.pack('<q', k))              # Int64 LE
                f.write(bytes(int(t)+1 for t in v))        # T→0, 0→1, 1→2
    except Exception as e:
        print(f"[NV] Warning: could not persist store: {e}")

def nv_load_file():
    if not os.path.exists(NV_FILE):
        return
    entry = 8 + REG_WIDTH
    try:
        with open(NV_FILE, 'rb') as f:
            raw = f.read()
        i = 0
        while i + entry <= len(raw):
            k = struct.unpack('<q', raw[i:i+8])[0]
            v = [Trit(b - 1) for b in raw[i+8:i+entry]]
            _nv_store[k] = v
            i += entry
        if _nv_store:
            print(f"[NV] Loaded {len(_nv_store)} entries from {NV_FILE}")
    except Exception as e:
        print(f"[NV] Warning: could not read store: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CPU
# ─────────────────────────────────────────────────────────────────────────────

class CPU:
    def __init__(self, mem_size: int = INSTR_LEN * 729):
        self.pc        = 1
        self.memory: List[Trit] = [ZERO] * mem_size
        # R0 = constant Zero (index 0 not stored; R1..R26 at indices 0..25)
        self.regs: List[List[Trit]] = [[ZERO]*REG_WIDTH for _ in range(N_REGS-1)]
        self.status    = ZERO
        self.running   = True
        self.int_flag  = NEG   # Neg=disabled, Zero=masked, Pos=enabled
        self.ivec_base = 0

    def get_reg(self, idx: int) -> List[Trit]:
        if idx == 0: return [ZERO]*REG_WIDTH
        return self.regs[max(0, min(idx-1, N_REGS-2))]

    def set_reg(self, idx: int, val: List[Trit]):
        if idx < 1 or idx > N_REGS-1:
            return
        padded = (val + [ZERO]*REG_WIDTH)[:REG_WIDTH]
        self.regs[idx-1] = padded

    def read_word(self, addr: int) -> List[Trit]:
        addr = max(1, min(addr, len(self.memory)))
        sl = self.memory[addr-1 : addr-1+REG_WIDTH]
        return (sl + [ZERO]*REG_WIDTH)[:REG_WIDTH]

    def write_word(self, addr: int, val: List[Trit]):
        for i in range(REG_WIDTH):
            a = addr + i - 1
            if 0 <= a < len(self.memory):
                self.memory[a] = val[i] if i < len(val) else ZERO

    def clamp_addr(self, n: int) -> int:
        return max(1, min(int(n), len(self.memory)))

    def stack_push(self, val: List[Trit]):
        sp = int(reg_int(self.get_reg(SP_REG)))
        sp -= REG_WIDTH
        if sp < 1:
            print("[STACK] Stack overflow!")
            return
        self.set_reg(SP_REG, sat(sp))
        self.write_word(sp, val)

    def stack_pop(self) -> List[Trit]:
        sp = int(reg_int(self.get_reg(SP_REG)))
        if sp > len(self.memory) - REG_WIDTH + 1:
            print("[STACK] Stack underflow!")
            return [ZERO]*REG_WIDTH
        val = self.read_word(sp)
        self.set_reg(SP_REG, sat(sp + REG_WIDTH))
        return val

    def reset(self):
        self.pc        = 1
        self.regs      = [[ZERO]*REG_WIDTH for _ in range(N_REGS-1)]
        self.status    = ZERO
        self.running   = True
        self.int_flag  = NEG
        self.ivec_base = 0
        print("[RESET] Registers and PC cleared.")


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTE ONE INSTRUCTION
# ─────────────────────────────────────────────────────────────────────────────

def _print_base(r: List[Trit], base: int):
    """Print register in alternate base encodings."""
    def enc(trits, group, offset, mod):
        n = len(trits) // group
        digits = []
        for i in range(n):
            sl = trits[i*group:(i+1)*group]
            v = bt_to_int(sl)
            digits.append((v + offset) % mod if mod else v + offset)
        return '(' + ', '.join(str(d) for d in reversed(digits)) + ')'

    s = trits_to_string(r)
    if   base == 9:
        out = enc(r, 2, 4, 9)
        print(f"Base-9  : {s}  →  {out}")
    elif base == 12:
        out = enc(r, 3, 6, 12)
        print(f"Base-12 : {s}  →  {out}")
    elif base == 27:
        out = enc(r, 3, 13, 0)
        print(f"Base-27 : {s}  →  {out}")
    elif base == 60:
        out = enc(r, 4, 30, 60)
        print(f"Base-60 : {s}  →  {out}")
    elif base == 81:
        out = enc(r, 4, 40, 0)
        print(f"Base-81 : {s}  →  {out}")
    else:
        print(f"PRINTB: unsupported base {base}")


def execute(cpu: CPU, receptor: Optional[ReceptorInterface]=None,
            trace: bool=False) -> bool:
    """
    Execute one instruction at cpu.pc.
    Returns True if execution should continue, False on HALT.
    """
    opcode, dst, src1, src2, src3, lane, flags, sub, imm_raw = decode_instr(cpu.memory, cpu.pc)
    imm_int  = bt_to_int(imm_raw)
    imm_addr = cpu.clamp_addr(imm_int)

    if trace:
        name = OPCODE_NAMES.get(opcode, f"???({opcode})")
        print(f"[TRACE] PC={cpu.pc:6d}  {name:12s} "
              f"dst={dst} src1={src1} src2={src2} imm={imm_int}")

    advanced = False   # set to True when we manually moved PC (branches)

    def gr(idx): return cpu.get_reg(idx)
    def ri(idx): return reg_int(gr(idx))
    def sr(idx, val): cpu.set_reg(idx, val); cpu.status = set_status(val)
    def sim_b(): return isinstance(receptor.backend if receptor else None, SimulatedBackend)

    # ── NOP ──────────────────────────────────────────────────────────────────
    if opcode == OP_NOP:
        pass

    # ── HALT ─────────────────────────────────────────────────────────────────
    elif opcode == OP_HALT:
        cpu.running = False
        return False

    # ── RESET ────────────────────────────────────────────────────────────────
    elif opcode == OP_RESET:
        cpu.reset()
        return True

    # ── PRINT / DEBUG ─────────────────────────────────────────────────────────
    elif opcode == OP_PRINT:
        r = gr(dst)
        print(f"R{dst} = {trits_to_string(r)}  ({reg_int(r)})")

    elif opcode == OP_DUMP:
        int_s = ("EN" if cpu.int_flag == POS else
                 "MASK" if cpu.int_flag == ZERO else "DIS")
        print("── DUMP ──────────────────────────────────────────────────────────")
        print(f"PC={cpu.pc}  STATUS={TRIT_SYM[cpu.status]}  "
              f"INT={int_s}  IVEC={cpu.ivec_base}")
        for i in range(1, N_REGS):
            r = cpu.get_reg(i)
            print(f"R{i:<2d} = {trits_to_string(r)}  ({reg_int(r)})")
        print("─────────────────────────────────────────────────────────────────")

    elif opcode == OP_PRINTI:
        print(str(imm_int))

    elif opcode == OP_PRINTB:
        _print_base(gr(dst), int(imm_int))

    elif opcode == OP_PRINTS:
        addr = cpu.clamp_addr(ri(dst))
        chars = []
        while addr >= 1 and addr + 2 <= len(cpu.memory):
            v = bt_to_int(cpu.memory[addr-1:addr+2])
            if v == 0: break
            chars.append(chr(v)); addr += 3
        print(''.join(chars))

    # ── COMPARE & BRANCH ──────────────────────────────────────────────────────
    elif opcode == OP_CMP:
        diff = sat_add(gr(src1), tritwise_not(gr(src2)))
        cpu.status = set_status(diff)

    elif opcode == OP_CMPI:
        diff = sat_add(gr(src1), sat(-imm_int))
        cpu.status = set_status(diff)

    elif opcode == OP_MIN:
        a, b = gr(src1), gr(src2)
        val = a if ri(src1) <= ri(src2) else b
        sr(dst, val)

    elif opcode == OP_MAX:
        a, b = gr(src1), gr(src2)
        val = a if ri(src1) >= ri(src2) else b
        sr(dst, val)

    elif opcode == OP_JMP:  cpu.pc = imm_addr; return True
    elif opcode == OP_JEZ:
        if cpu.status == ZERO: cpu.pc = imm_addr; return True
    elif opcode == OP_JNZ:
        if cpu.status != ZERO: cpu.pc = imm_addr; return True
    elif opcode == OP_JGT:
        if cpu.status == POS:  cpu.pc = imm_addr; return True
    elif opcode == OP_JLT:
        if cpu.status == NEG:  cpu.pc = imm_addr; return True
    elif opcode == OP_JGEZ:
        if cpu.status != NEG:  cpu.pc = imm_addr; return True
    elif opcode == OP_JLEZ:
        if cpu.status != POS:  cpu.pc = imm_addr; return True

    # ── SHIFT & ROTATE ────────────────────────────────────────────────────────
    elif opcode == OP_LSHIFT:  sr(dst, shift_left(gr(src1)))
    elif opcode == OP_RSHIFT:  sr(dst, shift_right(gr(src1)))
    elif opcode == OP_LSHIFTN:
        n = abs(int(reg_int(gr(src2))))
        sr(dst, shift_left(gr(src1), n))
    elif opcode == OP_RSHIFTN:
        n = abs(int(reg_int(gr(src2))))
        sr(dst, shift_right(gr(src1), n))
    elif opcode == OP_ROTL:  sr(dst, rotate_left(gr(src1)))
    elif opcode == OP_ROTR:  sr(dst, rotate_right(gr(src1)))

    # ── KLEENE LOGIC ──────────────────────────────────────────────────────────
    elif opcode == OP_TNOT:  sr(dst, tritwise_not(gr(src1)))
    elif opcode == OP_TNAND: sr(dst, tritwise(gr(src1), gr(src2), tNAND))
    elif opcode == OP_TNOR:  sr(dst, tritwise(gr(src1), gr(src2), tNOR))
    elif opcode == OP_TXNOR: sr(dst, tritwise(gr(src1), gr(src2), tXNOR))
    elif opcode == OP_TIMP:  sr(dst, tritwise(gr(src1), gr(src2), tIMP))
    elif opcode == OP_TMUX:
        a = gr(src1); b = gr(src2)
        val = (a if cpu.status == POS else
               b if cpu.status == ZERO else
               tritwise_not(a))
        sr(dst, val)
    elif opcode == OP_TMAJ:
        val = [tMAJ(gr(src1)[i], gr(src2)[i], gr(src3)[i])
               for i in range(REG_WIDTH)]
        sr(dst, val)
    elif opcode == OP_TCONS: sr(dst, tritwise(gr(src1), gr(src2), tCONS))
    elif opcode == OP_TSEL:
        rc_idx = max(0, min(sub, N_REGS-1))
        sel = reg_int(gr(src1))
        val = (gr(src2)   if sel < 0 else
               gr(src3)   if sel == 0 else
               gr(rc_idx))
        sr(dst, val)

    # ── ARITHMETIC & LOGIC ────────────────────────────────────────────────────
    elif opcode == OP_TXOR:  sr(dst, tritwise(gr(src1), gr(src2), tXOR))
    elif opcode == OP_TXORI: sr(dst, tritwise(gr(src1), sat(imm_int), tXOR))
    elif opcode == OP_TOR:   sr(dst, tritwise(gr(src1), gr(src2), tOR))
    elif opcode == OP_TORI:  sr(dst, tritwise(gr(src1), sat(imm_int), tOR))
    elif opcode == OP_TAND:  sr(dst, tritwise(gr(src1), gr(src2), tAND))
    elif opcode == OP_TANDI: sr(dst, tritwise(gr(src1), sat(imm_int), tAND))

    elif opcode == OP_DIV:
        dv = ri(src2)
        if dv == 0:
            cpu.status = NEG
            print(f"DIV/0: R{dst} unchanged, status=Neg")
        else:
            sr(dst, sat(ri(src1) // dv))

    elif opcode == OP_DIVI:
        if imm_int == 0:
            cpu.status = NEG
            print(f"DIVI/0: R{dst} unchanged")
        else:
            sr(dst, sat(int(ri(src1)) // int(imm_int)))

    elif opcode == OP_MOD:
        dv = ri(src2)
        if dv == 0:
            cpu.status = NEG
            print(f"MOD/0: R{dst} unchanged, status=Neg")
        else:
            # Sign follows dividend (BT convention)
            a, b = int(ri(src1)), int(dv)
            sr(dst, sat(int(math.remainder(a, b)) if b != 0 else 0))

    elif opcode == OP_MODI:
        if imm_int == 0:
            cpu.status = NEG
        else:
            a, b = int(ri(src1)), int(imm_int)
            r_val = a - (a // b) * b   # truncated toward zero
            sr(dst, sat(r_val))

    elif opcode == OP_MUL:
        sr(dst, sat(ri(src1) * ri(src2)))
    elif opcode == OP_MULI:
        sr(dst, sat(ri(src1) * imm_int))

    elif opcode == OP_STORE:
        cpu.write_word(imm_addr, gr(src1))
    elif opcode == OP_STORER:
        cpu.write_word(cpu.clamp_addr(ri(src2)), gr(src1))
    elif opcode == OP_STOREI:
        cpu.write_word(cpu.clamp_addr(ri(src1)), sat(imm_int))

    elif opcode == OP_LOAD:
        sr(dst, cpu.read_word(imm_addr))
    elif opcode == OP_LOADI:
        sr(dst, sat(imm_int))
    elif opcode == OP_LOADR:
        sr(dst, cpu.read_word(cpu.clamp_addr(ri(src1))))

    elif opcode == OP_MOV:
        sr(dst, gr(src1))
    elif opcode == OP_XCHG:
        a, b = gr(dst), gr(src1)
        cpu.set_reg(dst,  b); cpu.set_reg(src1, a)
        cpu.status = set_status(b)

    elif opcode == OP_ADD:
        sr(dst, sat_add(gr(src1), gr(src2)))
    elif opcode == OP_ADDI:
        sr(dst, sat_add(gr(src1), sat(imm_int)))
    elif opcode == OP_SUB:
        sr(dst, sat_add(gr(src1), tritwise_not(gr(src2))))
    elif opcode == OP_SUBI:
        sr(dst, sat_add(gr(src1), sat(-imm_int)))
    elif opcode == OP_NEG:
        sr(dst, tritwise_not(gr(src1)))
    elif opcode == OP_ABS:
        sr(dst, abs_reg(gr(src1)))
    elif opcode == OP_INC:
        sr(dst, sat_add(gr(dst), sat(1)))
    elif opcode == OP_DEC:
        sr(dst, sat_add(gr(dst), sat(-1)))
    elif opcode == OP_SIGN:
        n = ri(src1)
        sr(dst, sat(1 if n > 0 else -1 if n < 0 else 0))
    elif opcode == OP_SSET:
        n = ri(src1)
        cpu.status = (POS if n > 0 else NEG if n < 0 else ZERO)

    # ── INDEXED ADDRESSING (v3.1) ─────────────────────────────────────────────
    elif opcode == OP_LOADX:
        addr = cpu.clamp_addr(ri(src1) + imm_int)
        sr(dst, cpu.read_word(addr))
    elif opcode == OP_LOADRR:
        addr = cpu.clamp_addr(ri(src1) + ri(src2))
        sr(dst, cpu.read_word(addr))
    elif opcode == OP_STOREX:
        addr = cpu.clamp_addr(ri(src2) + imm_int)
        cpu.write_word(addr, gr(src1))
    elif opcode == OP_STORERR:
        addr = cpu.clamp_addr(ri(src1) + ri(src2))
        cpu.write_word(addr, gr(dst))

    # ── TRIT MANIPULATION (v3.1) ──────────────────────────────────────────────
    elif opcode == OP_TGET:
        pos = max(0, min(int(imm_int), REG_WIDTH-1))
        t   = gr(src1)[pos]
        val = [ZERO]*REG_WIDTH; val[0] = t
        cpu.set_reg(dst, val); cpu.status = t

    elif opcode == OP_TSET:
        pos  = max(0, min(int(imm_int), REG_WIDTH-1))
        base = list(gr(src1))
        base[pos] = gr(src2)[0]   # LST of src2
        sr(dst, base)

    elif opcode == OP_TSWAP:
        pos_a = max(0, min(int(imm_int), REG_WIDTH-1))
        pos_b = max(0, min(int(sub),     REG_WIDTH-1))
        base  = list(gr(src1))
        base[pos_a], base[pos_b] = base[pos_b], base[pos_a]
        sr(dst, base)

    # ── STACK & SUBROUTINES (v3.1) ────────────────────────────────────────────
    elif opcode == OP_PUSH:
        cpu.stack_push(gr(src1))
    elif opcode == OP_POP:
        val = cpu.stack_pop(); sr(dst, val)
    elif opcode == OP_CALL:
        cpu.stack_push(sat(cpu.pc + INSTR_LEN))
        cpu.pc = imm_addr; return True
    elif opcode == OP_RET:
        target = int(reg_int(cpu.stack_pop()))
        cpu.pc = cpu.clamp_addr(target); return True

    elif opcode == OP_INT_EN:
        cpu.int_flag = POS; print("[INT] Interrupts enabled.")
    elif opcode == OP_INT_DIS:
        cpu.int_flag = NEG; print("[INT] Interrupts disabled.")
    elif opcode == OP_IVEC:
        cpu.ivec_base = imm_addr
        print(f"[IVEC] Interrupt vector base → {cpu.ivec_base}")
    elif opcode == OP_IRET:
        target = int(reg_int(cpu.stack_pop()))
        cpu.int_flag = POS
        cpu.pc = cpu.clamp_addr(target); return True

    # ── HARDWARE RECEPTOR ─────────────────────────────────────────────────────
    elif opcode == OP_RECEP:
        ch   = max(0, min(int(imm_int), (receptor.backend.n_channels - 1) if receptor else 0))
        trit = (receptor.sample()[ch] if receptor
                else random.choice([NEG, ZERO, POS]))
        cpu.set_reg(dst, sat(int(trit))); cpu.status = trit

    elif opcode == OP_SENSE:
        n_s = max(1, int(imm_int))
        if receptor:
            for _ in range(n_s): receptor.sample()
            mv = receptor.majority_vote(n_s)
            trit = mv[0] if mv else ZERO
        else:
            trit = random.choice([NEG, ZERO, POS])
        cpu.set_reg(dst, sat(int(trit))); cpu.status = trit

    elif opcode == OP_SAMP_DB:
        trit = receptor.sample()[0] if receptor else random.choice([NEG, ZERO, POS])
        r = list(gr(dst)); r[0] = trit
        cpu.set_reg(dst, r); cpu.status = trit

    elif opcode == OP_SETTH_P:
        if receptor:
            v = float(ri(src1)) / 1000.0
            receptor.pos_threshold = v
            print(f"[SETTH_P] Positive threshold → {v:.4f} V")

    elif opcode == OP_SETTH_N:
        if receptor:
            v = float(ri(src1)) / 1000.0
            receptor.neg_threshold = v
            print(f"[SETTH_N] Negative threshold → {v:.4f} V")

    elif opcode == OP_RCLEAR:
        if receptor:
            receptor.history.clear(); receptor.sample_count = 0
            print("[RCLEAR] Receptor history flushed.")

    elif opcode == OP_RSTAT:
        if receptor:
            nc = max(-13, min(receptor.backend.n_channels, 13))
            sc = receptor.sample_count % 9841
            cpu.set_reg(dst, sat(nc + sc * 27))

    elif opcode in (OP_QUERY_I2C, OP_WRITE_I2C,
                    OP_QUERY_SPI, OP_WRITE_SPI,
                    OP_GPIO_READ, OP_GPIO_WRITE):
        if receptor:
            if opcode == OP_QUERY_I2C and isinstance(receptor.backend, ADS1115Backend):
                v = receptor.backend._read_ch(max(0, min(int(imm_int), 3)))
                sr(dst, sat(round(v * 1000)))
            elif opcode == OP_QUERY_SPI and isinstance(receptor.backend, MCP3008Backend):
                v = receptor.backend._read_ch(max(0, min(int(imm_int), 7)))
                sr(dst, sat(round(v * 1000)))
            elif opcode == OP_GPIO_READ and isinstance(receptor.backend, GPIOBackend):
                vs = receptor.backend.read_voltages()
                ch = max(0, min(int(imm_int), len(vs)-1))
                sr(dst, sat(round(vs[ch])))
            elif opcode == OP_GPIO_WRITE and isinstance(receptor.backend, GPIOBackend):
                tval = gr(src1)[0]
                level = 1 if tval == POS else 0
                pin = max(0, min(int(imm_int), 200))
                try:
                    receptor.backend._gpio.output(pin, level)
                except Exception as e:
                    print(f"[GPIO_WRITE] pin={pin}: {e}")
            elif opcode == OP_WRITE_I2C and isinstance(receptor.backend, ADS1115Backend):
                reg_n = max(0, min(int(imm_int), 3))
                ival  = int(max(-32768, min(ri(src1), 32767)))
                try:
                    receptor.backend._bus.write_i2c_block_data(
                        receptor.backend.address, reg_n,
                        [(ival >> 8) & 0xFF, ival & 0xFF])
                    print(f"[WRITE_I2C] reg={reg_n} val={ival}")
                except Exception as e:
                    print(f"[WRITE_I2C] {e}")
            elif opcode == OP_WRITE_SPI and isinstance(receptor.backend, MCP3008Backend):
                print(f"[WRITE_SPI] reg={int(imm_int)} (no-op on MCP3008)")
            # USB backend: raw write for GPIO_WRITE
            elif opcode == OP_GPIO_WRITE and isinstance(receptor.backend, USBSerialBackend):
                tval = gr(src1)[0]
                receptor.backend.write(bytes([int(imm_int), int(tval)+1]))

    elif opcode == OP_COHERE:
        if receptor and isinstance(receptor.backend, SimulatedBackend):
            receptor.backend.coherence = max(0.0, min(float(imm_int)/1000.0, 1.0))
            print(f"[COHERE] ξ → {receptor.backend.coherence:.3f}")

    elif opcode == OP_ARRAY_N:
        if receptor and isinstance(receptor.backend, SimulatedBackend):
            receptor.backend.array_n = max(1, int(imm_int))
            print(f"[ARRAY_N] N → {receptor.backend.array_n}")

    elif opcode == OP_GAIN:
        if receptor and isinstance(receptor.backend, SimulatedBackend):
            g   = receptor.backend.operator_gain()
            val = sat(max(-9841, min(round(g), 9841)))
            sr(dst, val)
            print(f"[GAIN] ξ²N² = {g:.2e} → R{dst}")

    # ── NON-VOLATILE MEMORY (v3.1) ────────────────────────────────────────────
    elif opcode == OP_NVLOAD:
        val = nv_load(int(imm_int))
        sr(dst, val)
        print(f"[NV] Loaded key {imm_int} → R{dst}")

    elif opcode == OP_NVSTORE:
        nv_store(int(imm_int), gr(src1))
        print(f"[NV] Stored R{src1} → key {imm_int}")

    else:
        print(f"Unknown opcode {opcode} at pc={cpu.pc}")

    cpu.pc += INSTR_LEN
    return True


def run(cpu: CPU, max_cycles=100_000,
        receptor: Optional[ReceptorInterface]=None,
        trace: bool=False):
    cycles = 0
    while (cpu.running and
           1 <= cpu.pc <= len(cpu.memory) and
           cycles < max_cycles):
        if not execute(cpu, receptor=receptor, trace=trace):
            break
        cycles += 1
    if cycles >= max_cycles:
        print(f"Warning: max_cycles ({max_cycles}) reached without HALT")


# ─────────────────────────────────────────────────────────────────────────────
# TWO-PASS ASSEMBLER
# ─────────────────────────────────────────────────────────────────────────────

class AssemblyError(Exception): pass

def _parse_reg(s: str, context: str="") -> int:
    s = s.strip().upper()
    if len(s) >= 2 and s[0] == 'R':
        try:
            n = int(s[1:])
            if 0 <= n <= N_REGS-1:
                return n
        except ValueError: pass
    raise AssemblyError(f"Expected register R0–R{N_REGS-1}, got: '{s}'{context}")

def _parse_arg(s: str, labels: Dict[str,int], context: str="") -> int:
    s = s.strip()
    # Integer literal
    try: return int(s)
    except ValueError: pass
    # Label reference
    key = s.upper()
    if key in labels:
        return labels[key]
    raise AssemblyError(f"Unknown argument or label: '{s}'{context}")

def parse_line(line: str, labels: Dict[str,int], pc: int) -> Optional[List[Trit]]:
    """Assemble one source line into 81 trits, or return None for blank/label."""
    # Strip comments
    line = re.sub(r';.*', '', line).strip().upper()
    if not line: return None
    if line.endswith(':'):
        return None  # label definition — handled in pass 1

    parts = line.split()
    if not parts: return None
    cmd = parts[0]
    np  = len(parts) - 1

    def r(i): return _parse_reg(parts[i], f" (arg {i} of {cmd})")
    def a(i): return _parse_arg(parts[i], labels, f" (arg {i} of {cmd})")
    def ai(i): return assemble_instr

    try:
        # Control
        if cmd == "NOP":    return assemble_instr(OP_NOP)
        if cmd == "HALT":   return assemble_instr(OP_HALT)
        if cmd == "RESET":  return assemble_instr(OP_RESET)
        if cmd == "DUMP":   return assemble_instr(OP_DUMP)
        if cmd == "RCLEAR": return assemble_instr(OP_RCLEAR)

        # Print / Debug
        if cmd == "PRINT"   and np>=1: return assemble_instr(OP_PRINT,  r(1))
        if cmd == "PRINTS"  and np>=1: return assemble_instr(OP_PRINTS, r(1))
        if cmd == "PRINTI"  and np>=1: return assemble_instr(OP_PRINTI, 0,0,0, imm=a(1))
        if cmd == "PRINTB"  and np>=2: return assemble_instr(OP_PRINTB, r(1),0,0, imm=a(2))

        # Data Movement
        if cmd == "LOAD"    and np>=2: return assemble_instr(OP_LOAD,   r(1),0,0, imm=a(2))
        if cmd == "LOADI"   and np>=2: return assemble_instr(OP_LOADI,  r(1),0,0, imm=a(2))
        if cmd == "LOADR"   and np>=2: return assemble_instr(OP_LOADR,  r(1),r(2))
        if cmd == "STORE"   and np>=2: return assemble_instr(OP_STORE,  0,r(1),0, imm=a(2))
        if cmd == "STORER"  and np>=2: return assemble_instr(OP_STORER, 0,r(1),r(2))
        if cmd == "STOREI"  and np>=2: return assemble_instr(OP_STOREI, 0,r(1),0, imm=a(2))
        if cmd == "MOV"     and np>=2: return assemble_instr(OP_MOV,    r(1),r(2))
        if cmd == "XCHG"    and np>=2: return assemble_instr(OP_XCHG,   r(1),r(2))

        # Indexed Addressing (v3.1)
        if cmd == "LOADX"   and np>=3: return assemble_instr(OP_LOADX,   r(1),r(2),0, imm=a(3))
        if cmd == "LOADRR"  and np>=3: return assemble_instr(OP_LOADRR,  r(1),r(2),r(3))
        if cmd == "STOREX"  and np>=3: return assemble_instr(OP_STOREX,  0,r(1),r(2), imm=a(3))
        if cmd == "STORERR" and np>=3: return assemble_instr(OP_STORERR, r(1),r(2),r(3))

        # Arithmetic
        if cmd == "ADD"   and np>=3: return assemble_instr(OP_ADD,   r(1),r(2),r(3))
        if cmd == "ADDI"  and np>=3: return assemble_instr(OP_ADDI,  r(1),r(2),0, imm=a(3))
        if cmd == "SUB"   and np>=3: return assemble_instr(OP_SUB,   r(1),r(2),r(3))
        if cmd == "SUBI"  and np>=3: return assemble_instr(OP_SUBI,  r(1),r(2),0, imm=a(3))
        if cmd == "MUL"   and np>=3: return assemble_instr(OP_MUL,   r(1),r(2),r(3))
        if cmd == "MULI"  and np>=3: return assemble_instr(OP_MULI,  r(1),r(2),0, imm=a(3))
        if cmd == "DIV"   and np>=3: return assemble_instr(OP_DIV,   r(1),r(2),r(3))
        if cmd == "DIVI"  and np>=3: return assemble_instr(OP_DIVI,  r(1),r(2),0, imm=a(3))
        if cmd == "MOD"   and np>=3: return assemble_instr(OP_MOD,   r(1),r(2),r(3))
        if cmd == "MODI"  and np>=3: return assemble_instr(OP_MODI,  r(1),r(2),0, imm=a(3))
        if cmd == "INC"   and np>=1: return assemble_instr(OP_INC,   r(1))
        if cmd == "DEC"   and np>=1: return assemble_instr(OP_DEC,   r(1))
        if cmd == "NEG"   and np>=2: return assemble_instr(OP_NEG,   r(1),r(2))
        if cmd == "ABS"   and np>=2: return assemble_instr(OP_ABS,   r(1),r(2))
        if cmd == "SIGN"  and np>=2: return assemble_instr(OP_SIGN,  r(1),r(2))
        if cmd == "SSET"  and np>=1: return assemble_instr(OP_SSET,  0,r(1))
        if cmd == "MIN"   and np>=3: return assemble_instr(OP_MIN,   r(1),r(2),r(3))
        if cmd == "MAX"   and np>=3: return assemble_instr(OP_MAX,   r(1),r(2),r(3))

        # Kleene Logic
        if cmd == "TNOT"  and np>=2: return assemble_instr(OP_TNOT,  r(1),r(2))
        if cmd == "TAND"  and np>=3: return assemble_instr(OP_TAND,  r(1),r(2),r(3))
        if cmd == "TANDI" and np>=3: return assemble_instr(OP_TANDI, r(1),r(2),0, imm=a(3))
        if cmd == "TOR"   and np>=3: return assemble_instr(OP_TOR,   r(1),r(2),r(3))
        if cmd == "TORI"  and np>=3: return assemble_instr(OP_TORI,  r(1),r(2),0, imm=a(3))
        if cmd == "TXOR"  and np>=3: return assemble_instr(OP_TXOR,  r(1),r(2),r(3))
        if cmd == "TXORI" and np>=3: return assemble_instr(OP_TXORI, r(1),r(2),0, imm=a(3))
        if cmd == "TNAND" and np>=3: return assemble_instr(OP_TNAND, r(1),r(2),r(3))
        if cmd == "TNOR"  and np>=3: return assemble_instr(OP_TNOR,  r(1),r(2),r(3))
        if cmd == "TXNOR" and np>=3: return assemble_instr(OP_TXNOR, r(1),r(2),r(3))
        if cmd == "TIMP"  and np>=3: return assemble_instr(OP_TIMP,  r(1),r(2),r(3))
        if cmd == "TMUX"  and np>=3: return assemble_instr(OP_TMUX,  r(1),r(2),r(3))
        if cmd == "TMAJ"  and np>=4: return assemble_instr(OP_TMAJ,  r(1),r(2),r(3),r(4))
        if cmd == "TCONS" and np>=3: return assemble_instr(OP_TCONS, r(1),r(2),r(3))
        if cmd == "TSEL"  and np>=5: return assemble_instr(OP_TSEL,  r(1),r(2),r(3),r(4), sub=r(5))

        # Trit Manipulation (v3.1)
        if cmd == "TGET"  and np>=3: return assemble_instr(OP_TGET,  r(1),r(2),0, imm=a(3))
        if cmd == "TSET"  and np>=4: return assemble_instr(OP_TSET,  r(1),r(2),r(3), imm=a(4))
        if cmd == "TSWAP" and np>=4: return assemble_instr(OP_TSWAP, r(1),r(2),0, sub=a(3), imm=a(4))

        # Shift & Rotate
        if cmd == "LSHIFT"  and np>=2: return assemble_instr(OP_LSHIFT,  r(1),r(2))
        if cmd == "RSHIFT"  and np>=2: return assemble_instr(OP_RSHIFT,  r(1),r(2))
        if cmd == "LSHIFTN" and np>=3: return assemble_instr(OP_LSHIFTN, r(1),r(2),r(3))
        if cmd == "RSHIFTN" and np>=3: return assemble_instr(OP_RSHIFTN, r(1),r(2),r(3))
        if cmd == "ROTL"    and np>=2: return assemble_instr(OP_ROTL,    r(1),r(2))
        if cmd == "ROTR"    and np>=2: return assemble_instr(OP_ROTR,    r(1),r(2))

        # Compare & Branch
        if cmd == "CMP"  and np>=2: return assemble_instr(OP_CMP,  0,r(1),r(2))
        if cmd == "CMPI" and np>=2: return assemble_instr(OP_CMPI, 0,r(1),0, imm=a(2))
        if cmd == "JMP"  and np>=1: return assemble_instr(OP_JMP,  0,0,0, imm=a(1))
        if cmd == "JEZ"  and np>=1: return assemble_instr(OP_JEZ,  0,0,0, imm=a(1))
        if cmd == "JNZ"  and np>=1: return assemble_instr(OP_JNZ,  0,0,0, imm=a(1))
        if cmd == "JGT"  and np>=1: return assemble_instr(OP_JGT,  0,0,0, imm=a(1))
        if cmd == "JLT"  and np>=1: return assemble_instr(OP_JLT,  0,0,0, imm=a(1))
        if cmd == "JGEZ" and np>=1: return assemble_instr(OP_JGEZ, 0,0,0, imm=a(1))
        if cmd == "JLEZ" and np>=1: return assemble_instr(OP_JLEZ, 0,0,0, imm=a(1))

        # Stack & Subroutines (v3.1)
        if cmd == "PUSH"    and np>=1: return assemble_instr(OP_PUSH,    0,r(1))
        if cmd == "POP"     and np>=1: return assemble_instr(OP_POP,     r(1))
        if cmd == "CALL"    and np>=1: return assemble_instr(OP_CALL,    0,0,0, imm=a(1))
        if cmd == "RET":               return assemble_instr(OP_RET)
        if cmd == "INT_EN":            return assemble_instr(OP_INT_EN)
        if cmd == "INT_DIS":           return assemble_instr(OP_INT_DIS)
        if cmd == "IVEC"    and np>=1: return assemble_instr(OP_IVEC,    0,0,0, imm=a(1))
        if cmd == "IRET":              return assemble_instr(OP_IRET)

        # Hardware Receptor
        if cmd == "RECEP"     and np>=2: return assemble_instr(OP_RECEP,     r(1),0,0, imm=a(2))
        if cmd == "SENSE"     and np>=2: return assemble_instr(OP_SENSE,     r(1),0,0, imm=a(2))
        if cmd == "SAMP_DB"   and np>=1: return assemble_instr(OP_SAMP_DB,  r(1))
        if cmd == "SETTH_P"   and np>=1: return assemble_instr(OP_SETTH_P,  0,r(1))
        if cmd == "SETTH_N"   and np>=1: return assemble_instr(OP_SETTH_N,  0,r(1))
        if cmd == "RSTAT"     and np>=1: return assemble_instr(OP_RSTAT,    r(1))
        if cmd == "COHERE"    and np>=1: return assemble_instr(OP_COHERE,   0,0,0, imm=a(1))
        if cmd == "ARRAY_N"   and np>=1: return assemble_instr(OP_ARRAY_N,  0,0,0, imm=a(1))
        if cmd == "GAIN"      and np>=1: return assemble_instr(OP_GAIN,     r(1))
        if cmd == "QUERY_I2C" and np>=2: return assemble_instr(OP_QUERY_I2C,r(1),0,0, imm=a(2))
        if cmd == "WRITE_I2C" and np>=2: return assemble_instr(OP_WRITE_I2C,0,r(1),0, imm=a(2))
        if cmd == "QUERY_SPI" and np>=2: return assemble_instr(OP_QUERY_SPI,r(1),0,0, imm=a(2))
        if cmd == "WRITE_SPI" and np>=2: return assemble_instr(OP_WRITE_SPI,0,r(1),0, imm=a(2))
        if cmd == "GPIO_READ" and np>=2: return assemble_instr(OP_GPIO_READ, r(1),0,0, imm=a(2))
        if cmd == "GPIO_WRITE"and np>=2: return assemble_instr(OP_GPIO_WRITE,0,r(1),0, imm=a(2))

        # Non-Volatile Memory (v3.1)
        if cmd == "NVLOAD"  and np>=2: return assemble_instr(OP_NVLOAD,  r(1),0,0, imm=a(2))
        if cmd == "NVSTORE" and np>=2: return assemble_instr(OP_NVSTORE, 0,r(1),0, imm=a(2))

    except AssemblyError:
        raise
    except Exception as e:
        raise AssemblyError(f"{cmd}: {e}")

    raise AssemblyError(f"Unknown mnemonic or wrong argument count: '{line}'")


def assemble_program(lines: List[str]) -> Tuple[List[Trit], Dict[str,int], List[str]]:
    """
    Two-pass assembler.
    Returns (code_trits, labels_dict, errors_list).
    Instruction N (0-based) starts at trit address 1 + N*81.
    """
    labels: Dict[str, int] = {}
    filtered: List[Tuple[int,str]] = []
    errors: List[str] = []
    pc = 1

    # Pass 1 — collect labels
    for lineno, raw in enumerate(lines, 1):
        clean = re.sub(r';.*', '', raw).strip().upper()
        if not clean: continue
        if clean.endswith(':'):
            label = clean[:-1].strip()
            if label: labels[label] = pc
        else:
            filtered.append((lineno, raw))
            pc += INSTR_LEN

    # Pass 2 — assemble
    code: List[Trit] = []
    for lineno, raw in filtered:
        try:
            instr = parse_line(raw, labels, len(code)+1)
            if instr is not None:
                code.extend(instr)
            else:
                # blank or label — skip (already counted in pass 1)
                pass
        except AssemblyError as e:
            errors.append(f"  line {lineno}: {e}\n    → {raw.rstrip()}")

    return code, labels, errors


def load_program(cpu: CPU, code: List[Trit], start: int=1):
    for i, trit in enumerate(code):
        addr = start - 1 + i
        if 0 <= addr < len(cpu.memory):
            cpu.memory[addr] = trit


# ─────────────────────────────────────────────────────────────────────────────
# MONITOR DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

def monitor(cpu: CPU, prev_regs: Optional[List[List[Trit]]]=None,
            receptor: Optional[ReceptorInterface]=None):
    opcode, dst, src1, src2, src3, _, _, sub, imm = decode_instr(cpu.memory, cpu.pc)
    op_name = OPCODE_NAMES.get(opcode, f"???({opcode})")
    int_s   = ("EN" if cpu.int_flag == POS else
               "MASK" if cpu.int_flag == ZERO else "DIS")
    imm_int = bt_to_int(imm)

    print("\n── CPU STATE ──────────────────────────────────────────────────────────")
    print(f"PC={cpu.pc:<8d} STATUS={TRIT_SYM[cpu.status]}  INT={int_s}  IVEC={cpu.ivec_base}")
    print(f"Next: {op_name} (dst={dst} src1={src1} src2={src2} src3={src3} imm={imm_int})")
    print(f"{'Reg':<5} │ {'Trit string (81 chars, MST→LST)':<83} │ {'Decimal':>30} │ diff")
    print("──────┼" + "─"*84 + "┼" + "─"*31 + "┼──────")

    for i in range(1, N_REGS):
        r   = cpu.get_reg(i)
        dec = reg_int(r)
        tag = ""
        if prev_regs and r != prev_regs[i-1]:
            tag = " (changed)"
        sp_tag = "  ← SP" if i == SP_REG else ""
        print(f" R{i:<3d} │ {trits_to_string(r)} │ {str(dec):>30} │{tag}{sp_tag}")

    print("───────────────────────────────────────────────────────────────────────")
    if receptor:
        receptor.show_status()


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-LINE REPL INPUT
# ─────────────────────────────────────────────────────────────────────────────

BLOCK_STARTS = {
    'LOOP', 'IF', 'BEGIN', 'PROC', 'FUNC', 'SUB', 'SECTION', 'MACRO'
}
BLOCK_ENDS   = {'END', 'ENDLOOP', 'ENDIF', 'ENDPROC', 'ENDFUNC', 'ENDSUB'}
# We treat a trailing ':' as a label, not a block end

def _looks_incomplete(lines: List[str]) -> bool:
    """
    Heuristic: a buffer is incomplete if it contains a label definition
    or a CALL with a forward label, without a HALT/RET to terminate it,
    OR if the user explicitly typed a block-opener keyword.
    """
    joined = '\n'.join(lines)
    # Has an explicit HALT or RET → complete
    for end_word in ('HALT', 'RET', 'IRET'):
        if re.search(rf'\b{end_word}\b', joined, re.IGNORECASE):
            return False
    # Has a label definition → likely a multi-line program, keep buffering
    if re.search(r'^\s*\w+\s*:', joined, re.MULTILINE):
        return True
    # Has a CALL or jump to a named label (not a number) → incomplete
    if re.search(r'\b(CALL|JMP|JEZ|JNZ|JGT|JLT|JGEZ|JLEZ)\s+[A-Za-z]', joined):
        return True
    return False


def repl_read_block() -> Optional[List[str]]:
    """
    Read one logical block from stdin.
    - Single-line instructions run immediately.
    - Multi-line programs (labels, CALL, jumps-to-names) buffer until
      the user enters a blank line after at least one HALT/RET, or types
      END on its own line.
    Returns None on EOF / quit.
    """
    buffer: List[str] = []
    prompt_main = "\nT-AL> "
    prompt_cont = "   .. "

    while True:
        prompt = prompt_main if not buffer else prompt_cont
        try:
            line = input(prompt)
        except EOFError:
            if buffer:
                return buffer
            return None

        stripped = line.strip()

        # Quit signals
        if stripped.lower() in ('quit', 'exit', 'q') and not buffer:
            return None

        # END keyword forces execution of current buffer
        if stripped.upper() == 'END' and buffer:
            return buffer

        # Blank line: if buffering and buffer looks complete → execute
        if stripped == '':
            if buffer:
                if not _looks_incomplete(buffer):
                    return buffer
                # else keep buffering (show continuation prompt)
            # else: plain blank line, ignore
            continue

        buffer.append(line)

        # Single-line self-contained instruction: execute immediately
        # (no label defs, no forward branches, not a comment or directive)
        if len(buffer) == 1:
            upper = stripped.upper()
            cmd = upper.split()[0] if upper.split() else ''
            # Sandbox meta-commands
            if cmd in ('RUN', 'STEP', 'MONITOR', 'STATUS', 'MEMDUMP',
                       'CONVERT', 'RECEPTOR', 'TRACE', 'RESET', 'HELP',
                       'CLEAR', 'LABELS', 'PORTS'):
                return buffer
            # Single instruction with no label and no forward branch
            if not _looks_incomplete(buffer):
                return buffer
        # else: keep buffering


# ─────────────────────────────────────────────────────────────────────────────
# HELP TEXT
# ─────────────────────────────────────────────────────────────────────────────

HELP = """
Ternary-AL v3.1 — Native Python Interpreter
════════════════════════════════════════════════════════════════════════
ARCHITECTURE
  Registers : R0..R26  (27; R0 = constant Zero)
  Word width : 81 trits (Tesseract)   ≈ ±2.21×10³⁸
  Instr width: 81 trits (27-27-27 Tesseract layout)
  Immediate  : ±3,812,798,742,493  (27-trit Triple)
  Memory     : flat trit array, word-addressed in 81-trit units
  R26 = SP (Stack Pointer) by convention; grows downward

REPL USAGE
  • Type any assembly instruction and press Enter → executes immediately
  • Multi-line programs: type multiple lines; a blank line after a
    complete program (with HALT/RET) executes the whole block
  • Labels auto-trigger multi-line mode; type END to force execution
  • Arrow keys scroll command history (readline)

SANDBOX COMMANDS  (case-insensitive)
  run                  Re-run from PC=1 (full assemble + run)
  step                 Execute one instruction; show monitor
  reset                Clear regs + PC; memory preserved
  monitor              Full CPU state display
  status               STATUS trit and PC only
  trace [on|off]       Toggle per-instruction trace
  memdump ADDR LEN     Dump LEN Tesseract words from trit-address ADDR
  convert N            Show N in balanced ternary + all base encodings
  receptor             Show receptor layer status
  labels               List all labels and their trit addresses
  ports                List available serial/USB ports
  clear                Reset CPU and clear memory
  help                 This message
  quit / exit / q      Shut down

INSTRUCTION SYNTAX  (no commas; case-insensitive)
  DATA MOVEMENT:  LOAD LOADI LOADR LOADX LOADRR
                  STORE STORER STOREI STOREX STORERR  MOV XCHG
  ARITHMETIC:     ADD ADDI SUB SUBI MUL MULI DIV DIVI MOD MODI
                  INC DEC NEG ABS SIGN MIN MAX SSET
  KLEENE LOGIC:   TNOT TAND TANDI TOR TORI TXOR TXORI
                  TNAND TNOR TXNOR TIMP TMUX TMAJ TCONS TSEL
  TRIT OPS:       TGET TSET TSWAP
  SHIFT/ROTATE:   LSHIFT RSHIFT LSHIFTN RSHIFTN ROTL ROTR
  COMPARE/BRANCH: CMP CMPI JMP JEZ JNZ JGT JLT JGEZ JLEZ
  STACK/CALL:     PUSH POP CALL RET INT_EN INT_DIS IVEC IRET
  DEBUG/IO:       PRINT PRINTI PRINTB PRINTS DUMP NOP HALT RESET RCLEAR
  HARDWARE:       RECEP SENSE SAMP_DB SETTH_P SETTH_N RSTAT
                  QUERY_I2C WRITE_I2C QUERY_SPI WRITE_SPI
                  GPIO_READ GPIO_WRITE COHERE ARRAY_N GAIN
  NON-VOLATILE:   NVLOAD NVSTORE

LABELS
  LOOP:          ; defines label LOOP at current address
  JMP LOOP       ; reference by name in any branch

TRIT SYMBOLS:  T = Neg (−1)   0 = Zero   1 = Pos (+1)
════════════════════════════════════════════════════════════════════════
"""

# ─────────────────────────────────────────────────────────────────────────────
# SANDBOX  (interactive REPL)
# ─────────────────────────────────────────────────────────────────────────────

def sandbox(receptor: Optional[ReceptorInterface]=None,
            show_monitor: bool=True,
            trace: bool=False):
    cpu       = CPU()
    prev_regs = deepcopy(cpu.regs)
    # Accumulated program lines for multi-run support
    program_lines: List[str] = []
    _trace = [trace]

    nv_load_file()

    print("\n=== Ternary-AL v3.1 — Native Python Interpreter ===")
    print("Type 'help' for commands.  Multi-line programs buffer until HALT/RET + blank line.")
    if receptor:
        print(f"Receptor: {type(receptor.backend).__name__}")
    if show_monitor:
        monitor(cpu, receptor=receptor)

    while True:
        block = repl_read_block()
        if block is None:
            break

        if not block:
            continue

        cmd0 = block[0].strip().split()[0].upper() if block[0].strip() else ''

        # ── Sandbox meta-commands ─────────────────────────────────────────────
        if len(block) == 1 and cmd0 in (
            'RUN','STEP','MONITOR','STATUS','MEMDUMP','CONVERT',
            'RECEPTOR','TRACE','RESET','HELP','CLEAR','LABELS','PORTS'
        ):
            raw = block[0].strip()
            parts = raw.split()

            if cmd0 == 'HELP':
                print(HELP)

            elif cmd0 == 'QUIT' or cmd0 == 'EXIT':
                break

            elif cmd0 == 'RUN':
                if program_lines:
                    code, lbl, errs = assemble_program(program_lines)
                    if errs:
                        print("Assembler errors:")
                        for e in errs: print(e)
                    else:
                        cpu2 = CPU()
                        load_program(cpu2, code)
                        prev_regs = deepcopy(cpu2.regs)
                        run(cpu2, receptor=receptor, trace=_trace[0])
                        cpu = cpu2
                        if show_monitor:
                            monitor(cpu, prev_regs, receptor)
                else:
                    print("No program loaded. Enter assembly first.")

            elif cmd0 == 'STEP':
                prev_regs = deepcopy(cpu.regs)
                if cpu.pc >= 1 and cpu.pc <= len(cpu.memory):
                    execute(cpu, receptor=receptor, trace=_trace[0])
                if show_monitor:
                    monitor(cpu, prev_regs, receptor)

            elif cmd0 == 'MONITOR':
                monitor(cpu, prev_regs, receptor)

            elif cmd0 == 'STATUS':
                print(f"PC={cpu.pc}  STATUS={TRIT_SYM[cpu.status]}")

            elif cmd0 == 'RECEPTOR':
                if receptor:
                    receptor.show_status()
                else:
                    print("No receptor attached.")

            elif cmd0 == 'TRACE':
                flag = parts[1].lower() if len(parts) > 1 else ''
                _trace[0] = True if flag == 'on' else (False if flag == 'off' else not _trace[0])
                print(f"Trace {'ON' if _trace[0] else 'OFF'}")

            elif cmd0 == 'RESET':
                prev_regs = deepcopy(cpu.regs)
                cpu.reset()
                if show_monitor:
                    monitor(cpu, prev_regs, receptor)

            elif cmd0 == 'CLEAR':
                cpu = CPU()
                program_lines = []
                prev_regs = deepcopy(cpu.regs)
                print("[CLEAR] CPU and memory reset. Program buffer cleared.")
                if show_monitor:
                    monitor(cpu, prev_regs, receptor)

            elif cmd0 == 'MEMDUMP':
                if len(parts) < 3:
                    print("Usage: memdump ADDR LEN")
                else:
                    addr = int(parts[1]); ln = int(parts[2])
                    print(f"Memory dump from {addr}, {ln} Tesseract word(s):")
                    for i in range(ln):
                        w   = cpu.read_word(addr + i*REG_WIDTH)
                        dec = reg_int(w)
                        print(f"  [{addr+i*REG_WIDTH:>6d}] {trits_to_string(w)}  ({dec})")

            elif cmd0 == 'CONVERT':
                if len(parts) < 2:
                    print("Usage: convert N")
                else:
                    n = int(parts[1])
                    tr = int_to_bt(n, 9)
                    print(f"Decimal {n}  →  {trits_to_string(tr)}")
                    for base in (9, 12, 27, 60, 81):
                        _print_base(int_to_bt(n, 81), base)

            elif cmd0 == 'LABELS':
                if program_lines:
                    _, lbl, _ = assemble_program(program_lines)
                    if lbl:
                        print("Labels:")
                        for k, v in sorted(lbl.items(), key=lambda x: x[1]):
                            print(f"  {k:<20s} → trit addr {v}")
                    else:
                        print("No labels defined.")
                else:
                    print("No program loaded.")

            elif cmd0 == 'PORTS':
                ports = list_serial_ports()
                if ports:
                    print("Available serial/USB ports:")
                    for p in ports: print(f"  {p}")
                else:
                    print("No serial/USB ports found.")

            continue

        # ── Assemble & execute block ──────────────────────────────────────────
        # Check if this is a single instruction (no labels, no jumps to names)
        is_single = (len(block) == 1 and not _looks_incomplete(block))

        if is_single:
            # Single instruction: assemble into current PC slot and execute
            try:
                instr = parse_line(block[0], {}, cpu.pc)
                if instr:
                    load_program(cpu, instr, cpu.pc)
                    prev_regs = deepcopy(cpu.regs)
                    execute(cpu, receptor=receptor, trace=_trace[0])
                    if show_monitor:
                        monitor(cpu, prev_regs, receptor)
            except AssemblyError as e:
                print(f"Assembler error: {e}")
        else:
            # Multi-line program: two-pass assemble from scratch
            program_lines = block
            code, labels, errs = assemble_program(program_lines)
            if errs:
                print(f"Assembler errors ({len(errs)}):")
                for e in errs: print(e)
            else:
                n_instr = len(code) // INSTR_LEN
                print(f"Assembled {n_instr} instruction(s).  "
                      f"Labels: {list(labels.keys()) or 'none'}")
                cpu2 = CPU()
                load_program(cpu2, code)
                prev_regs = deepcopy(cpu2.regs)
                run(cpu2, receptor=receptor, trace=_trace[0])
                cpu = cpu2
                if show_monitor:
                    monitor(cpu, prev_regs, receptor)

    print("\n=== Ternary-AL Interpreter Shut Down ===")
    if receptor:
        receptor.backend.close()


# ─────────────────────────────────────────────────────────────────────────────
# FILE MODE
# ─────────────────────────────────────────────────────────────────────────────

def run_file(path: str,
             receptor: Optional[ReceptorInterface]=None,
             show_monitor: bool=True,
             trace: bool=False,
             step: bool=False):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: file not found: {path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading {path}: {e}")
        sys.exit(1)

    code, labels, errs = assemble_program(lines)
    if errs:
        print(f"Assembler errors in {path}:")
        for e in errs: print(e)
        sys.exit(1)

    n_instr = len(code) // INSTR_LEN
    print(f"[T-AL] {path}: {n_instr} instruction(s).  "
          f"Labels: {list(labels.keys()) or 'none'}")

    cpu = CPU()
    load_program(cpu, code)
    nv_load_file()
    prev_regs = deepcopy(cpu.regs)

    if step:
        # Single-step mode: show monitor, wait for Enter each step
        print("Step mode. Press Enter to advance, 'q' to quit.")
        while cpu.running and 1 <= cpu.pc <= len(cpu.memory):
            monitor(cpu, prev_regs, receptor)
            try:
                inp = input("[step]> ").strip().lower()
            except EOFError:
                break
            if inp in ('q', 'quit', 'exit'):
                break
            prev_regs = deepcopy(cpu.regs)
            execute(cpu, receptor=receptor, trace=trace)
    else:
        run(cpu, receptor=receptor, trace=trace)

    if show_monitor:
        monitor(cpu, prev_regs, receptor)

    if receptor:
        receptor.backend.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ternary-AL v3.1 — Native Python Interpreter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tal.py                        Interactive REPL
  python tal.py program.tal            Run file
  python tal.py program.tal --trace    Run with per-instruction trace
  python tal.py program.tal --step     Single-step with monitor
  python tal.py --no-monitor           REPL without monitor display
  python tal.py --receptor usb         Force USB/serial receptor
  python tal.py --receptor usb:/dev/ttyUSB0  Specific USB port
  python tal.py --receptor sim         Force simulated receptor
  python tal.py --list-ports           List available serial/USB ports
        """)

    parser.add_argument('file', nargs='?', help='T-AL source file to run')
    parser.add_argument('--trace',      action='store_true', help='Per-instruction trace')
    parser.add_argument('--step',       action='store_true', help='Single-step execution')
    parser.add_argument('--no-monitor', action='store_true', help='Suppress monitor display')
    parser.add_argument('--receptor',   default='auto',
                        help='Receptor mode: auto | sim | usb | usb:PORT | i2c | spi | gpio')
    parser.add_argument('--list-ports', action='store_true', help='List serial/USB ports and exit')
    args = parser.parse_args()

    if args.list_ports:
        ports = list_serial_ports()
        if ports:
            print("Available serial/USB ports:")
            for p in ports: print(f"  {p}")
        else:
            print("No serial/USB ports found.")
        sys.exit(0)

    # ── Build receptor ────────────────────────────────────────────────────────
    rec_mode = args.receptor.lower()
    backend: Optional[ReceptorBackend] = None

    if rec_mode == 'sim':
        backend = SimulatedBackend()
        print("[Receptor] Simulated stochastic backend")

    elif rec_mode.startswith('usb'):
        port = None
        if ':' in rec_mode:
            port = args.receptor.split(':', 1)[1]   # preserve original case
        backend = detect_hardware(force_usb_port=port, verbose=True)

    elif rec_mode == 'i2c':
        try:
            backend = ADS1115Backend()
        except Exception as e:
            print(f"[Receptor] ADS1115 failed: {e}. Falling back to simulated.")
            backend = SimulatedBackend()

    elif rec_mode == 'spi':
        try:
            backend = MCP3008Backend()
        except Exception as e:
            print(f"[Receptor] MCP3008 failed: {e}. Falling back to simulated.")
            backend = SimulatedBackend()

    elif rec_mode == 'gpio':
        print("[Receptor] GPIO backend requires pin configuration in code. "
              "Using simulated.")
        backend = SimulatedBackend()

    else:  # auto
        backend = detect_hardware(verbose=True)

    receptor = ReceptorInterface(backend)
    show_monitor = not args.no_monitor

    # ── Run ───────────────────────────────────────────────────────────────────
    if args.file:
        run_file(args.file, receptor=receptor,
                 show_monitor=show_monitor,
                 trace=args.trace,
                 step=args.step)
    else:
        sandbox(receptor=receptor,
                show_monitor=show_monitor,
                trace=args.trace)


if __name__ == '__main__':
    main()
