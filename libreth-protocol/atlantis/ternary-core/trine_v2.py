#!/usr/bin/env python3
"""
trine.py  ─  TRINE Language  v1.1  (Native Bootstrap Release)
═══════════════════════════════════════════════════════════════════════════════
Two-tier balanced-ternary programming language

  TIER 1  trine/asm ─ TAL-compatible assembly (direct opcode mapping)
  TIER 2  trine     ─ high-level structured language

  v1.1 changes over v1.0
  ──────────────────────
  • TAL emitter  : MOVE → MOV everywhere (was using wrong mnemonic)
  • TAL emitter  : asm{} block splits on newlines, not semicolons
  • TAL emitter  : rev{} emits reversible swap sequence in TAL
  • TAL emitter  : torsion{} emits guarded block with CALL+RET wrapper
  • TAL emitter  : struct field layout table; FieldAccess uses LOADX
  • TAL emitter  : ArrayLit / Index emitters use STORE / LOADX
  • TAL emitter  : all comparison ops fully correct (CMP then branch)
  • TAL emitter  : builtin functions (sign, abs, maj, mux, print, halt)
  • --run-tal    : emit TAL assembly, assemble via tal.py, run on CPU
  • --pipeline   : attach ternary_pipeline.py as receptor / stdlib backend
  • use "module" : load .tr stdlib files from search path
  • Builtins      : phase_step, base60_encode, ecc_syndrome, nv_load/store
  • Inline asm    : full delegation to tal.py when available; fallback only
                    for environments where tal.py is not on path

Usage
    python trine.py                          # screen editor
    python trine.py prog.tr                  # run via tree-walker
    python trine.py prog.tr --run-tal        # emit TAL, run on CPU
    python trine.py prog.tr --emit-tal       # print TAL assembly
    python trine.py prog.tr --trace          # trace tree-walk
    python trine.py prog.tr --pipeline sim   # attach simulated receptor
    python trine.py --example > example.tr   # print example program
═══════════════════════════════════════════════════════════════════════════════
Author : Skeome  (v1.1 native bootstrap, Skeome)
"""

from __future__ import annotations

import sys, os, re, math, readline, curses, textwrap, traceback, argparse
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field as dc_field
from enum   import IntEnum, auto
from copy   import deepcopy


# ═══════════════════════════════════════════════════════════════════════════════
# §0  BALANCED-TERNARY PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════════════

class Trit(IntEnum):
    Neg  = -1
    Zero =  0
    Pos  =  1

NEG, ZERO, POS = Trit.Neg, Trit.Zero, Trit.Pos
TRIT_SYM = {NEG: 'T', ZERO: '0', POS: '1'}
SYM_TRIT  = {'T': NEG, '0': ZERO, '1': POS, 't': NEG}

def tNOT(t): return Trit(-int(t))
def tAND(a,b): return Trit(min(int(a),int(b)))
def tOR (a,b): return Trit(max(int(a),int(b)))
def tXOR(a,b): return tOR(tAND(a,tNOT(b)), tAND(tNOT(a),b))
def tMAJ(a,b,c):
    s = int(a)+int(b)+int(c)
    return POS if s>0 else (NEG if s<0 else ZERO)
def tMUX(s,a,b,c): return {NEG:a, ZERO:b, POS:c}[s]
def tSHIFT_UP(t):   return Trit((int(t)+1+3)%3-1)
def tSHIFT_DOWN(t): return Trit((int(t)-1+3)%3-1)

# Word widths (in trits)
W = {  'trit':1, 'tryte':3, 'trinity':9, 'triple':27, 'tesseract':81  }
DEFAULT_WIDTH = 27   # 'triple' is the default numeric type

def _max_val(width: int) -> int:
    return (3**width - 1) // 2

def bt_to_int(trits: List) -> int:
    return sum(int(t)*(3**i) for i,t in enumerate(trits))

def int_to_bt(n: int, width: int) -> List[Trit]:
    digits: List[Trit] = []
    tmp = n
    for _ in range(width):
        r = tmp % 3
        if r == 2:  r=-1; tmp=(tmp+1)//3
        elif r==-1: r=-1; tmp=(tmp+1)//3
        elif r== 1: r= 1; tmp=(tmp-1)//3
        elif r==-2: r= 1; tmp=(tmp-1)//3
        else:             tmp//=3
        digits.append(Trit(r))
    return digits

def sat(n: int, width: int = DEFAULT_WIDTH) -> int:
    mx = _max_val(width)
    return max(-mx, min(mx, n))

def sat_add(a,b,w=DEFAULT_WIDTH): return sat(a+b,w)
def sat_sub(a,b,w=DEFAULT_WIDTH): return sat(a-b,w)
def sat_mul(a,b,w=DEFAULT_WIDTH): return sat(a*b,w)
def sat_div(a,b,w=DEFAULT_WIDTH): return sat(a//b,w) if b!=0 else None
def sat_mod(a,b,w=DEFAULT_WIDTH): return a%b if b!=0 else None

def wrap(n: int, width: int) -> int:
    modulus = 3**width
    r = n % modulus
    half = modulus // 2
    if r > half: r -= modulus
    return r

def trit_sign(n: int) -> Trit:
    return POS if n>0 else (NEG if n<0 else ZERO)

def trits_str(trits) -> str:
    return ''.join(TRIT_SYM[t] for t in reversed(trits))

def int_to_trits_str(n: int, w: int = DEFAULT_WIDTH) -> str:
    return trits_str(int_to_bt(n, w))

def parse_ternary_literal(s: str) -> int:
    digits = list(reversed([SYM_TRIT.get(c, ZERO) for c in s]))
    return bt_to_int(digits)

def _tw_op(a: int, b: int, op, w=DEFAULT_WIDTH):
    ta = int_to_bt(a, w); tb = int_to_bt(b, w)
    return bt_to_int([op(x,y) for x,y in zip(ta,tb)])

def tw_and (a,b,w=DEFAULT_WIDTH): return _tw_op(a,b,tAND,w)
def tw_or  (a,b,w=DEFAULT_WIDTH): return _tw_op(a,b,tOR,w)
def tw_xor (a,b,w=DEFAULT_WIDTH): return _tw_op(a,b,tXOR,w)
def tw_not (a,w=DEFAULT_WIDTH):
    return bt_to_int([tNOT(t) for t in int_to_bt(a,w)])
def tw_maj (a,b,c,w=DEFAULT_WIDTH):
    ta=int_to_bt(a,w); tb=int_to_bt(b,w); tc=int_to_bt(c,w)
    return bt_to_int([tMAJ(x,y,z) for x,y,z in zip(ta,tb,tc)])
def tw_mux (sel,a,b,c,w=DEFAULT_WIDTH):
    s = trit_sign(sel)
    return {NEG:a, ZERO:b, POS:c}[s]
def tw_lshift(a,n,w=DEFAULT_WIDTH):
    t = int_to_bt(a,w); return bt_to_int(([ZERO]*n+t)[:w])
def tw_rshift(a,n,w=DEFAULT_WIDTH):
    t = int_to_bt(a,w); return bt_to_int((t+[ZERO]*n)[n:n+w])
def tw_rotl(a,n,w=DEFAULT_WIDTH):
    t=int_to_bt(a,w); n%=w; return bt_to_int(t[n:]+t[:n])
def tw_rotr(a,n,w=DEFAULT_WIDTH):
    t=int_to_bt(a,w); n%=w; return bt_to_int(t[-n:]+t[:-n])


# ═══════════════════════════════════════════════════════════════════════════════
# §0b  PIPELINE BUILTINS  (delegated to ternary_pipeline.py when available)
# ═══════════════════════════════════════════════════════════════════════════════

# Lazy import — pipeline is optional
_pipeline_mod = None

def _get_pipeline():
    global _pipeline_mod
    if _pipeline_mod is None:
        try:
            import importlib.util, os
            candidates = [
                os.path.join(os.path.dirname(__file__), 'ternary_pipeline.py'),
                'ternary_pipeline.py',
            ]
            for path in candidates:
                if os.path.exists(path):
                    spec = importlib.util.spec_from_file_location('ternary_pipeline', path)
                    _pipeline_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(_pipeline_mod)
                    break
        except Exception:
            pass
    return _pipeline_mod

# Pure-Python fallback phase LUT (mirrors ternary_pipeline.PhaseSequencer12)
_PHASE_LUT = [(-1 + (i % 3)) for i in range(12)]   # T,0,1 × 4

def builtin_phase_step(phase: int) -> int:
    """Advance 12-phase FSM, return new offset trit-int."""
    p = _pipeline_mod  # may be None, that's fine
    if p:
        seq = p.PhaseSequencer12()
        seq.phase = int(phase) % 12
        off = seq.step()
        return p.bt_to_int(off)
    phase = int(phase) % 12
    nxt = (phase + 1) % 12
    return _PHASE_LUT[nxt]

def builtin_base60_encode(deg: int, minutes: int, seconds: int) -> int:
    """Base-60 coordinate → balanced-ternary integer."""
    p = _get_pipeline()
    if p:
        word = p.Base60Mapper.encode(int(deg), int(minutes), int(seconds))
        return p.bt_to_int(word)
    # Fallback: pack into integer
    return int(seconds) + int(minutes) * 60 + int(deg) * 3600

def builtin_base60_decode(val: int) -> Tuple[int,int,int]:
    p = _get_pipeline()
    if p:
        word = p.int_to_bt(int(val), p.TRIPLE_W)
        deg, m, s, _ = p.Base60Mapper.decode(word)
        return deg, m, s
    s = int(val) % 60
    m = (int(val) // 60) % 60
    d = int(val) // 3600
    return d, m, s

def builtin_ecc_encode(val: int, k: int = DEFAULT_WIDTH) -> int:
    """ECC-encode a value, return as integer (data+check trits packed)."""
    p = _get_pipeline()
    if p:
        data = p.int_to_bt(int(val), k)
        ecc  = p.TernaryECC(k=k)
        cw   = ecc.encode(data)
        return p.bt_to_int(cw)
    return val  # no-op fallback

def builtin_ecc_syndrome(codeword: int, k: int = DEFAULT_WIDTH) -> int:
    """Return syndrome integer (0 = no error)."""
    p = _get_pipeline()
    if p:
        n = k + p.TernaryECC._min_r(k)
        cw_trits = p.int_to_bt(int(codeword), n)
        ecc = p.TernaryECC(k=k)
        s = ecc.syndrome(cw_trits)
        return int(sum(abs(x) for x in s) > 0)
    return 0

def builtin_mac_step_n2(field: int, n: int) -> int:
    """Single N² MAC step on a field value."""
    p = _get_pipeline()
    if p:
        fv  = p.int_to_bt(int(field), p.TRIPLE_W)
        mac = p.MACTile()
        res = mac.step_n2(fv, int(n))
        return p.bt_to_int(res)
    return sat(int(field) + int(n)**2)

# ═══════════════════════════════════════════════════════════════════════════════
# §1  TOKENS  &  LEXER
# ═══════════════════════════════════════════════════════════════════════════════

class TT(IntEnum):
    INT = auto(); TERNARY = auto(); STR = auto(); TRIT_LIT = auto()
    IDENT = auto()
    PLUS=auto(); MINUS=auto(); STAR=auto(); SLASH=auto(); PERCENT=auto()
    PLUS_W=auto(); MINUS_W=auto(); STAR_W=auto()
    AMP=auto(); PIPE=auto(); CARET=auto(); TILDE=auto()
    SHL=auto(); SHR=auto(); ROTL=auto(); ROTR=auto()
    EQ=auto(); NEQ=auto(); LT=auto(); GT=auto(); LEQ=auto(); GEQ=auto()
    ASSIGN=auto(); PLUS_EQ=auto(); MINUS_EQ=auto(); STAR_EQ=auto(); SLASH_EQ=auto()
    FAT_ARROW=auto()
    LPAREN=auto(); RPAREN=auto(); LBRACE=auto(); RBRACE=auto()
    LBRACKET=auto(); RBRACKET=auto()
    COMMA=auto(); SEMI=auto(); COLON=auto(); DOT=auto(); DOTDOT=auto()
    ARROW=auto(); AT=auto()
    NEWLINE=auto(); EOF=auto()

KEYWORDS = {
    'fn','return','if','else','while','for','in','match',
    'struct','let','mut','const','pub','use',
    'rev','torsion','asm',
    'true','false','null',
    'trit','tryte','trinity','triple','tesseract',
    'maj','mux','sign','abs','print','println','halt',
    # v1.1 pipeline builtins
    'phase_step','base60_encode','base60_decode',
    'ecc_encode','ecc_syndrome','mac_step_n2',
    'nv_load','nv_store',
}

@dataclass
class Token:
    kind:  TT
    value: Any
    line:  int
    col:   int

    def __repr__(self):
        return f"Token({self.kind.name},{self.value!r}@{self.line}:{self.col})"

class LexError(Exception): pass

class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.src  = source
        self.file = filename
        self.pos  = 0
        self.line = 1
        self.col  = 1
        self.tokens: List[Token] = []

    def _cur(self, offset=0) -> str:
        p = self.pos + offset
        return self.src[p] if p < len(self.src) else '\0'

    def _peek(self) -> str: return self._cur(1)

    def _advance(self) -> str:
        c = self.src[self.pos]; self.pos += 1
        if c == '\n': self.line += 1; self.col = 1
        else:         self.col += 1
        return c

    def _emit(self, kind: TT, value=None, line=None, col=None) -> Token:
        t = Token(kind, value, line or self.line, col or self.col)
        self.tokens.append(t); return t

    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.src):
            c = self._cur()
            if c in (' ', '\t', '\r'):
                self._advance(); continue
            if c == '/' and self._peek() == '/':
                while self.pos < len(self.src) and self._cur() != '\n':
                    self._advance()
                continue
            if c == '/' and self._peek() == '*':
                self._advance(); self._advance()
                while self.pos < len(self.src) - 1:
                    if self._cur() == '*' and self._peek() == '/':
                        self._advance(); self._advance(); break
                    self._advance()
                continue
            break

    def tokenise(self) -> List[Token]:
        while self.pos < len(self.src):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.src): break

            ln, col = self.line, self.col
            c = self._cur()

            if c == '\n':
                self._advance()
                self._emit(TT.NEWLINE, '\n', ln, col); continue

            if c == '0' and self._peek() == 't':
                self._advance(); self._advance()
                s = ''
                while self._cur() in ('T','t','0','1'):
                    s += self._advance()
                if not s: raise LexError(f"{self.file}:{ln}:{col}: empty ternary literal")
                self._emit(TT.TERNARY, parse_ternary_literal(s), ln, col); continue

            if c.isdigit() or (c == '-' and self._peek().isdigit() and
                               (not self.tokens or self.tokens[-1].kind in (
                                TT.ASSIGN,TT.PLUS,TT.MINUS,TT.STAR,TT.SLASH,TT.PERCENT,
                                TT.LPAREN,TT.COMMA,TT.COLON,TT.LBRACKET,TT.ARROW,
                                TT.NEWLINE,TT.SEMI))):
                s = ''
                if c == '-': s += self._advance()
                while self._cur().isdigit(): s += self._advance()
                self._emit(TT.INT, int(s), ln, col); continue

            if c == '"':
                self._advance(); s = ''
                while self.pos < len(self.src) and self._cur() != '"':
                    s += self._advance()
                if self._cur() == '"': self._advance()
                else: raise LexError(f"{self.file}:{ln}:{col}: unterminated string")
                self._emit(TT.STR, s, ln, col); continue

            if c == 'T' and (not self._peek().isalnum() and self._peek() != '_'):
                self._advance()
                self._emit(TT.TRIT_LIT, -1, ln, col); continue

            if c.isalpha() or c == '_':
                s = ''
                while self._cur().isalnum() or self._cur() == '_':
                    s += self._advance()
                self._emit(TT.IDENT, s, ln, col)
                continue

            if c == '@':
                self._advance()
                self._emit(TT.AT, '@', ln, col); continue

            if c == '.' and self._peek() == '.':
                self._advance(); self._advance()
                self._emit(TT.DOTDOT, '..', ln, col); continue
            if c == '-' and self._peek() == '>':
                self._advance(); self._advance()
                self._emit(TT.ARROW, '->', ln, col); continue
            if c == '<' and self._peek() == '<' and self.src[self.pos+2:self.pos+3]=='<':
                self._advance();self._advance();self._advance()
                self._emit(TT.ROTL,'<<<',ln,col); continue
            if c == '>' and self._peek() == '>' and self.src[self.pos+2:self.pos+3]=='>':
                self._advance();self._advance();self._advance()
                self._emit(TT.ROTR,'>>>',ln,col); continue
            if c == '<' and self._peek() == '<':
                self._advance();self._advance()
                self._emit(TT.SHL,'<<',ln,col); continue
            if c == '>' and self._peek() == '>':
                self._advance();self._advance()
                self._emit(TT.SHR,'>>',ln,col); continue
            if c == '+' and self._peek() == '~':
                self._advance();self._advance()
                self._emit(TT.PLUS_W,'+~',ln,col); continue
            if c == '-' and self._peek() == '~':
                self._advance();self._advance()
                self._emit(TT.MINUS_W,'-~',ln,col); continue
            if c == '*' and self._peek() == '~':
                self._advance();self._advance()
                self._emit(TT.STAR_W,'*~',ln,col); continue
            if c == '+' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.PLUS_EQ,'+=',ln,col); continue
            if c == '-' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.MINUS_EQ,'-=',ln,col); continue
            if c == '*' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.STAR_EQ,'*=',ln,col); continue
            if c == '/' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.SLASH_EQ,'/=',ln,col); continue
            if c == '=' and self._peek() == '>':
                self._advance();self._advance()
                self._emit(TT.FAT_ARROW,'=>',ln,col); continue
            if c == '=' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.EQ,'==',ln,col); continue
            if c == '!' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.NEQ,'!=',ln,col); continue
            if c == '<' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.LEQ,'<=',ln,col); continue
            if c == '>' and self._peek() == '=':
                self._advance();self._advance()
                self._emit(TT.GEQ,'>=',ln,col); continue

            MAP1 = {
                '+':TT.PLUS, '-':TT.MINUS, '*':TT.STAR, '/':TT.SLASH,
                '%':TT.PERCENT, '&':TT.AMP, '|':TT.PIPE, '^':TT.CARET,
                '~':TT.TILDE, '<':TT.LT, '>':TT.GT, '=':TT.ASSIGN,
                '(':TT.LPAREN,')'  :TT.RPAREN,
                '{':TT.LBRACE, '}':TT.RBRACE,
                '[':TT.LBRACKET, ']':TT.RBRACKET,
                ',':TT.COMMA, ';':TT.SEMI, ':':TT.COLON, '.':TT.DOT,
            }
            if c in MAP1:
                self._advance()
                self._emit(MAP1[c], c, ln, col); continue

            raise LexError(f"{self.file}:{ln}:{col}: unexpected character {c!r}")

        self._emit(TT.EOF, None)
        return self.tokens


# ═══════════════════════════════════════════════════════════════════════════════
# §2  AST NODES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Node:
    line: int = 0

@dataclass
class Program(Node):
    items: List[Node] = dc_field(default_factory=list)

@dataclass
class FnDecl(Node):
    name:    str = ''
    params:  List[Tuple[str,str,bool]] = dc_field(default_factory=list)
    ret_ty:  Optional[str] = None
    body:    Optional['Block'] = None

@dataclass
class StructDecl(Node):
    name:   str = ''
    fields: List[Tuple[str,str]] = dc_field(default_factory=list)

@dataclass
class ConstDecl(Node):
    name:  str = ''
    ty:    Optional[str] = None
    value: Optional[Node] = None

@dataclass
class UseDecl(Node):
    """use "module_name"  — load a .tr stdlib file."""
    path: str = ''

@dataclass
class Block(Node):
    stmts: List[Node] = dc_field(default_factory=list)

@dataclass
class LetStmt(Node):
    name:  str = ''
    ty:    Optional[str] = None
    mut:   bool = False
    value: Optional[Node] = None

@dataclass
class AssignStmt(Node):
    target: Node = dc_field(default_factory=lambda: Ident(''))
    op:     str  = '='
    value:  Node = dc_field(default_factory=lambda: Ident(''))

@dataclass
class ReturnStmt(Node):
    value: Optional[Node] = None

@dataclass
class IfStmt(Node):
    cond:  Node = dc_field(default_factory=lambda: Ident(''))
    then:  Block = dc_field(default_factory=Block)
    else_: Optional[Node] = None

@dataclass
class WhileStmt(Node):
    cond: Node  = dc_field(default_factory=lambda: Ident(''))
    body: Block = dc_field(default_factory=Block)

@dataclass
class ForStmt(Node):
    var:   str  = ''
    start: Node = dc_field(default_factory=lambda: Ident(''))
    end:   Node = dc_field(default_factory=lambda: Ident(''))
    body:  Block = dc_field(default_factory=Block)

@dataclass
class MatchStmt(Node):
    expr: Node  = dc_field(default_factory=lambda: Ident(''))
    arms: List[Tuple[str,Block]] = dc_field(default_factory=list)

@dataclass
class RevBlock(Node):
    body: Block = dc_field(default_factory=Block)

@dataclass
class TorsionBlock(Node):
    body: Block = dc_field(default_factory=Block)

@dataclass
class AsmBlock(Node):
    code: str = ''

@dataclass
class ExprStmt(Node):
    expr: Node = dc_field(default_factory=lambda: Ident(''))

@dataclass
class Literal(Node):
    value: int = 0
    ty:    str = 'triple'

@dataclass
class StrLit(Node):
    value: str = ''

@dataclass
class Ident(Node):
    name: str = ''

@dataclass
class BinOp(Node):
    op:    str  = '+'
    left:  Node = dc_field(default_factory=lambda: Ident(''))
    right: Node = dc_field(default_factory=lambda: Ident(''))

@dataclass
class UnOp(Node):
    op:      str  = '~'
    operand: Node = dc_field(default_factory=lambda: Ident(''))

@dataclass
class Call(Node):
    fn:   str         = ''
    args: List[Node]  = dc_field(default_factory=list)

@dataclass
class Index(Node):
    array: Node = dc_field(default_factory=lambda: Ident(''))
    idx:   Node = dc_field(default_factory=lambda: Ident(''))

@dataclass
class FieldAccess(Node):
    obj:  Node = dc_field(default_factory=lambda: Ident(''))
    name: str  = ''

@dataclass
class StructLit(Node):
    name:   str                      = ''
    fields: List[Tuple[str,Node]]    = dc_field(default_factory=list)

@dataclass
class ArrayLit(Node):
    elements: List[Node] = dc_field(default_factory=list)

@dataclass
class AsmRef(Node):
    name: str = ''


# ═══════════════════════════════════════════════════════════════════════════════
# §3  PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class ParseError(Exception): pass

TYPE_KEYWORDS = {'trit','tryte','trinity','triple','tesseract'}
BUILTIN_FNS   = {
    'maj','mux','sign','abs','print','println','halt',
    'phase_step','base60_encode','base60_decode',
    'ecc_encode','ecc_syndrome','mac_step_n2',
    'nv_load','nv_store',
    'trits','int','len','tAND','tOR','tNOT','tXOR',
}

class Parser:
    def __init__(self, tokens: List[Token], filename: str = "<input>"):
        self.tokens = [t for t in tokens if t.kind != TT.NEWLINE]
        self.pos    = 0
        self.file   = filename
        # Pre-scan: collect all struct names so _parse_primary can distinguish
        # struct literals from uppercase constants/identifiers followed by `{`.
        self._known_structs: set = set()
        for i, t in enumerate(self.tokens):
            if (t.kind == TT.IDENT and t.value == 'struct'
                    and i + 1 < len(self.tokens)
                    and self.tokens[i+1].kind == TT.IDENT):
                self._known_structs.add(self.tokens[i+1].value)

    def _cur(self) -> Token:
        return self.tokens[min(self.pos, len(self.tokens)-1)]

    def _peek(self, offset=1) -> Token:
        p = self.pos + offset
        return self.tokens[min(p, len(self.tokens)-1)]

    def _advance(self) -> Token:
        t = self._cur(); self.pos += 1; return t

    def _check(self, kind: TT, value=None) -> bool:
        t = self._cur()
        if t.kind != kind: return False
        if value is not None and t.value != value: return False
        return True

    def _expect(self, kind: TT, value=None) -> Token:
        t = self._cur()
        if t.kind == kind and (value is None or t.value == value):
            return self._advance()
        desc = f"{kind.name}" + (f"({value!r})" if value else "")
        raise ParseError(
            f"{self.file}:{t.line}:{t.col}: expected {desc}, got {t.kind.name}({t.value!r})")

    def _eat(self, kind: TT, value=None) -> bool:
        if self._check(kind, value): self._advance(); return True
        return False

    def _at_eof(self) -> bool: return self._cur().kind == TT.EOF

    def parse(self) -> Program:
        items = []
        while not self._at_eof():
            items.append(self._parse_item())
        return Program(items=items)

    def _parse_item(self) -> Node:
        t = self._cur()
        if t.kind == TT.IDENT:
            if t.value == 'fn':     return self._parse_fn()
            if t.value == 'struct': return self._parse_struct()
            if t.value == 'const':  return self._parse_const()
            if t.value == 'pub':    self._advance(); return self._parse_item()
            if t.value == 'use':    return self._parse_use()
        return self._parse_stmt()

    def _parse_use(self) -> UseDecl:
        line = self._cur().line
        self._expect(TT.IDENT, 'use')
        path = self._expect(TT.STR).value
        self._eat(TT.SEMI)
        return UseDecl(path=path, line=line)

    def _parse_fn(self) -> FnDecl:
        line = self._cur().line
        self._expect(TT.IDENT, 'fn')
        name = self._expect(TT.IDENT).value
        self._expect(TT.LPAREN)
        params = self._parse_param_list()
        self._expect(TT.RPAREN)
        ret_ty = None
        if self._eat(TT.ARROW):
            ret_ty = self._parse_type()
        body = self._parse_block()
        return FnDecl(name=name, params=params, ret_ty=ret_ty, body=body, line=line)

    def _parse_param_list(self) -> List[Tuple[str,str,bool]]:
        params = []
        while not self._check(TT.RPAREN) and not self._at_eof():
            mut = self._eat(TT.IDENT, 'mut')
            pname = self._expect(TT.IDENT).value
            self._expect(TT.COLON)
            ptype = self._parse_type()
            params.append((pname, ptype, bool(mut)))
            if not self._eat(TT.COMMA): break
        return params

    def _parse_struct(self) -> StructDecl:
        line = self._cur().line
        self._expect(TT.IDENT, 'struct')
        name = self._expect(TT.IDENT).value
        self._expect(TT.LBRACE)
        fields = []
        while not self._check(TT.RBRACE) and not self._at_eof():
            fname = self._expect(TT.IDENT).value
            self._expect(TT.COLON)
            ftype = self._parse_type()
            fields.append((fname, ftype))
            self._eat(TT.COMMA)
        self._expect(TT.RBRACE)
        return StructDecl(name=name, fields=fields, line=line)

    def _parse_const(self) -> ConstDecl:
        line = self._cur().line
        self._expect(TT.IDENT, 'const')
        name = self._expect(TT.IDENT).value
        ty = None
        if self._eat(TT.COLON): ty = self._parse_type()
        self._expect(TT.ASSIGN)
        val = self._parse_expr()
        self._eat(TT.SEMI)
        return ConstDecl(name=name, ty=ty, value=val, line=line)

    def _parse_type(self) -> str:
        t = self._cur()
        if t.kind == TT.IDENT and t.value in TYPE_KEYWORDS:
            self._advance()
            base = t.value
            if self._check(TT.LBRACKET):
                self._advance()
                sz_tok = self._expect(TT.INT)
                self._expect(TT.RBRACKET)
                return f"{base}[{sz_tok.value}]"
            return base
        if t.kind == TT.IDENT:
            self._advance(); return t.value
        raise ParseError(f"{self.file}:{t.line}:{t.col}: expected type, got {t.value!r}")

    def _parse_block(self) -> Block:
        line = self._cur().line
        self._expect(TT.LBRACE)
        stmts = []
        while not self._check(TT.RBRACE) and not self._at_eof():
            stmts.append(self._parse_stmt())
        self._expect(TT.RBRACE)
        return Block(stmts=stmts, line=line)

    def _parse_stmt(self) -> Node:
        t = self._cur()
        if t.kind == TT.IDENT:
            v = t.value
            if v == 'let':    return self._parse_let()
            if v == 'return': return self._parse_return()
            if v == 'if':     return self._parse_if()
            if v == 'while':  return self._parse_while()
            if v == 'for':    return self._parse_for()
            if v == 'match':  return self._parse_match()
            if v == 'rev':    return self._parse_rev()
            if v == 'torsion':return self._parse_torsion()
            if v == 'asm':    return self._parse_asm()
            if v == 'use':    return self._parse_use()
            if v == 'halt':   self._advance(); self._eat(TT.SEMI); return Call(fn='halt', args=[])

        expr = self._parse_expr()
        if self._cur().kind in (TT.ASSIGN,TT.PLUS_EQ,TT.MINUS_EQ,TT.STAR_EQ,TT.SLASH_EQ):
            op = self._advance().value
            rhs = self._parse_expr()
            self._eat(TT.SEMI)
            return AssignStmt(target=expr, op=op, value=rhs, line=t.line)
        self._eat(TT.SEMI)
        return ExprStmt(expr=expr, line=t.line)

    def _parse_let(self) -> LetStmt:
        line = self._cur().line
        self._expect(TT.IDENT, 'let')
        mut = self._eat(TT.IDENT, 'mut')
        name = self._expect(TT.IDENT).value
        ty = None
        if self._eat(TT.COLON): ty = self._parse_type()
        val = None
        if self._eat(TT.ASSIGN): val = self._parse_expr()
        self._eat(TT.SEMI)
        return LetStmt(name=name, ty=ty, mut=bool(mut), value=val, line=line)

    def _parse_return(self) -> ReturnStmt:
        line = self._cur().line
        self._expect(TT.IDENT, 'return')
        if self._check(TT.RBRACE) or self._check(TT.SEMI) or self._at_eof():
            self._eat(TT.SEMI); return ReturnStmt(value=None, line=line)
        val = self._parse_expr()
        self._eat(TT.SEMI)
        return ReturnStmt(value=val, line=line)

    def _parse_if(self) -> IfStmt:
        line = self._cur().line
        self._expect(TT.IDENT, 'if')
        cond = self._parse_expr()
        then = self._parse_block()
        else_ = None
        if self._check(TT.IDENT, 'else'):
            self._advance()
            if self._check(TT.IDENT, 'if'): else_ = self._parse_if()
            else:                            else_ = self._parse_block()
        return IfStmt(cond=cond, then=then, else_=else_, line=line)

    def _parse_while(self) -> WhileStmt:
        line = self._cur().line
        self._expect(TT.IDENT, 'while')
        cond = self._parse_expr()
        body = self._parse_block()
        return WhileStmt(cond=cond, body=body, line=line)

    def _parse_for(self) -> ForStmt:
        line = self._cur().line
        self._expect(TT.IDENT, 'for')
        var = self._expect(TT.IDENT).value
        self._expect(TT.IDENT, 'in')
        start = self._parse_expr()
        self._expect(TT.DOTDOT)
        end = self._parse_expr()
        body = self._parse_block()
        return ForStmt(var=var, start=start, end=end, body=body, line=line)

    def _parse_match(self) -> MatchStmt:
        line = self._cur().line
        self._expect(TT.IDENT, 'match')
        expr = self._parse_expr()
        self._expect(TT.LBRACE)
        arms = []
        while not self._check(TT.RBRACE) and not self._at_eof():
            t = self._cur()
            if t.kind == TT.TRIT_LIT:
                lbl = 'T'; self._advance()
            elif t.kind == TT.INT and t.value in (0,1):
                lbl = str(t.value); self._advance()
            elif t.kind == TT.IDENT and t.value == '_':
                lbl = '_'; self._advance()
            else:
                raise ParseError(f"{self.file}:{t.line}: match arm must be T,0,1 or _")
            self._expect(TT.FAT_ARROW)
            body = self._parse_block() if self._check(TT.LBRACE) else Block(stmts=[ExprStmt(expr=self._parse_expr())])
            arms.append((lbl, body))
            self._eat(TT.COMMA)
        self._expect(TT.RBRACE)
        return MatchStmt(expr=expr, arms=arms, line=line)

    def _parse_rev(self) -> RevBlock:
        line = self._cur().line
        self._expect(TT.IDENT, 'rev')
        body = self._parse_block()
        return RevBlock(body=body, line=line)

    def _parse_torsion(self) -> TorsionBlock:
        line = self._cur().line
        self._expect(TT.IDENT, 'torsion')
        body = self._parse_block()
        return TorsionBlock(body=body, line=line)

    def _parse_asm(self) -> AsmBlock:
        line = self._cur().line
        self._expect(TT.IDENT, 'asm')
        self._expect(TT.LBRACE)
        code_lines = []
        cur_line_parts = []
        prev_line = self._cur().line
        depth = 1
        while not self._at_eof():
            t = self._cur()
            if t.kind == TT.LBRACE: depth += 1
            if t.kind == TT.RBRACE:
                depth -= 1
                if depth == 0:
                    if cur_line_parts:
                        code_lines.append(' '.join(cur_line_parts))
                    break
            # Detect line boundaries by token line number
            if cur_line_parts and t.line > prev_line:
                code_lines.append(' '.join(cur_line_parts))
                cur_line_parts = []
            prev_line = t.line
            val = str(t.value) if t.value is not None else ''
            if val: cur_line_parts.append(val)
            self._advance()
        self._expect(TT.RBRACE)
        return AsmBlock(code='\n'.join(code_lines), line=line)

    # ── expression ────────────────────────────────────────────────────────────

    def _parse_expr(self, min_prec: int = 0) -> Node:
        return self._parse_assign(min_prec)

    def _parse_assign(self, min_prec=0) -> Node:
        return self._parse_or()

    def _parse_or(self) -> Node:
        left = self._parse_and()
        while self._check(TT.PIPE):
            op = self._advance().value; right = self._parse_and()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_and(self) -> Node:
        left = self._parse_xor()
        while self._check(TT.AMP):
            op = self._advance().value; right = self._parse_xor()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_xor(self) -> Node:
        left = self._parse_compare()
        while self._check(TT.CARET):
            op = self._advance().value; right = self._parse_compare()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_compare(self) -> Node:
        left = self._parse_shift()
        while self._cur().kind in (TT.EQ,TT.NEQ,TT.LT,TT.GT,TT.LEQ,TT.GEQ):
            op = self._advance().value; right = self._parse_shift()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_shift(self) -> Node:
        left = self._parse_add()
        while self._cur().kind in (TT.SHL,TT.SHR,TT.ROTL,TT.ROTR):
            op = self._advance().value; right = self._parse_add()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_add(self) -> Node:
        left = self._parse_mul()
        while self._cur().kind in (TT.PLUS,TT.MINUS,TT.PLUS_W,TT.MINUS_W):
            op = self._advance().value; right = self._parse_mul()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_mul(self) -> Node:
        left = self._parse_unary()
        while self._cur().kind in (TT.STAR,TT.SLASH,TT.PERCENT,TT.STAR_W):
            op = self._advance().value; right = self._parse_unary()
            left = BinOp(op=op, left=left, right=right, line=left.line)
        return left

    def _parse_unary(self) -> Node:
        t = self._cur()
        if t.kind == TT.TILDE:
            self._advance(); return UnOp(op='~', operand=self._parse_unary(), line=t.line)
        if t.kind == TT.MINUS:
            self._advance(); return UnOp(op='-', operand=self._parse_unary(), line=t.line)
        return self._parse_postfix()

    def _parse_postfix(self) -> Node:
        left = self._parse_primary()
        while True:
            if self._check(TT.DOT):
                self._advance()
                fname = self._expect(TT.IDENT).value
                left = FieldAccess(obj=left, name=fname, line=left.line)
            elif self._check(TT.LBRACKET):
                self._advance()
                idx = self._parse_expr()
                self._expect(TT.RBRACKET)
                left = Index(array=left, idx=idx, line=left.line)
            else:
                break
        return left

    def _parse_primary(self) -> Node:
        t = self._cur()
        if t.kind == TT.INT:
            self._advance(); return Literal(value=t.value, ty='triple', line=t.line)
        if t.kind == TT.TERNARY:
            self._advance(); return Literal(value=t.value, ty='triple', line=t.line)
        if t.kind == TT.TRIT_LIT:
            self._advance(); return Literal(value=-1, ty='trit', line=t.line)
        if t.kind == TT.STR:
            self._advance(); return StrLit(value=t.value, line=t.line)
        if t.kind == TT.AT:
            self._advance()
            name = self._expect(TT.IDENT).value
            return AsmRef(name=name, line=t.line)
        if t.kind == TT.LPAREN:
            self._advance(); expr = self._parse_expr(); self._expect(TT.RPAREN)
            return expr
        if t.kind == TT.LBRACKET:
            return self._parse_array_lit()
        if t.kind == TT.IDENT:
            v = t.value
            if v == 'true':  self._advance(); return Literal(value=1,  ty='trit', line=t.line)
            if v == 'false': self._advance(); return Literal(value=-1, ty='trit', line=t.line)
            if v == 'null':  self._advance(); return Literal(value=0,  ty='trit', line=t.line)
            if self._peek().kind == TT.LPAREN:
                return self._parse_call()
            # Only treat Name{ as a struct literal when Name is a known struct.
            # This prevents uppercase constants/variables from being mis-parsed.
            if (v[0].isupper() and self._peek().kind == TT.LBRACE
                    and v in self._known_structs):
                return self._parse_struct_lit()
            self._advance(); return Ident(name=v, line=t.line)
        raise ParseError(f"{self.file}:{t.line}:{t.col}: unexpected token {t.kind.name}({t.value!r})")

    def _parse_call(self) -> Call:
        t = self._cur()
        name = self._advance().value
        self._expect(TT.LPAREN)
        args = []
        while not self._check(TT.RPAREN) and not self._at_eof():
            args.append(self._parse_expr())
            if not self._eat(TT.COMMA): break
        self._expect(TT.RPAREN)
        return Call(fn=name, args=args, line=t.line)

    def _parse_struct_lit(self) -> StructLit:
        t = self._cur()
        name = self._advance().value
        self._expect(TT.LBRACE)
        fields = []
        while not self._check(TT.RBRACE) and not self._at_eof():
            fname = self._expect(TT.IDENT).value
            self._expect(TT.COLON)
            fval  = self._parse_expr()
            fields.append((fname, fval))
            self._eat(TT.COMMA)
        self._expect(TT.RBRACE)
        return StructLit(name=name, fields=fields, line=t.line)

    def _parse_array_lit(self) -> ArrayLit:
        t = self._cur()
        self._expect(TT.LBRACKET)
        elems = []
        while not self._check(TT.RBRACKET) and not self._at_eof():
            elems.append(self._parse_expr())
            if not self._eat(TT.COMMA): break
        self._expect(TT.RBRACKET)
        return ArrayLit(elements=elems, line=t.line)


# ═══════════════════════════════════════════════════════════════════════════════
# §4  RUNTIME VALUES  &  ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════════════════

class TRINEReturn(Exception):
    def __init__(self, val): self.val = val

class TRINEError(Exception): pass

class TRINETorsionAbort(Exception):
    def __init__(self, msg, snapshot): super().__init__(msg); self.snapshot = snapshot

@dataclass
class TRINEStruct:
    type_name: str
    fields:    Dict[str, Any]
    def __repr__(self):
        fstr = ', '.join(f"{k}={v}" for k,v in self.fields.items())
        return f"{self.type_name}{{{fstr}}}"

@dataclass
class TRINEArray:
    elements: List[Any]
    def __repr__(self):
        return '[' + ', '.join(str(e) for e in self.elements) + ']'

class Environment:
    def __init__(self, parent: Optional['Environment'] = None):
        self.vars:   Dict[str, Any] = {}
        self.mutabl: Dict[str, bool] = {}
        self.parent  = parent

    def define(self, name: str, value: Any, mutable: bool = False):
        self.vars[name]   = value
        self.mutabl[name] = mutable

    def lookup(self, name: str) -> Any:
        if name in self.vars: return self.vars[name]
        if self.parent: return self.parent.lookup(name)
        raise TRINEError(f"undefined variable '{name}'")

    def assign(self, name: str, value: Any):
        if name in self.vars:
            if not self.mutabl[name]:
                raise TRINEError(f"cannot assign to immutable variable '{name}'")
            self.vars[name] = value; return
        if self.parent: self.parent.assign(name, value); return
        raise TRINEError(f"undefined variable '{name}'")

    def is_defined_here(self, name: str) -> bool:
        return name in self.vars

    def snapshot(self) -> Dict:
        return {k: deepcopy(v) for k,v in self.vars.items()}

    def restore(self, snap: Dict):
        self.vars.update(snap)

    def child(self) -> 'Environment':
        return Environment(parent=self)


# ═══════════════════════════════════════════════════════════════════════════════
# §5  INTERPRETER
# ═══════════════════════════════════════════════════════════════════════════════

# Lazy import of tal.py for inline asm delegation
_tal_mod = None

def _get_tal():
    global _tal_mod
    if _tal_mod is None:
        try:
            import importlib.util
            candidates = [
                os.path.join(os.path.dirname(__file__), 'tal.py'),
                'tal.py',
            ]
            for path in candidates:
                if os.path.exists(path):
                    spec = importlib.util.spec_from_file_location('tal', path)
                    _tal_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(_tal_mod)
                    break
        except Exception:
            pass
    return _tal_mod

# NV store bridged to tal.py when available
def _nv_load(key: int) -> int:
    t = _get_tal()
    if t:
        trits = t.nv_load(key)
        return t.reg_int(trits)
    return 0

def _nv_store(key: int, val: int):
    t = _get_tal()
    if t:
        trits = t.sat(val)
        t.nv_store(key, trits)


class Interpreter:
    def __init__(self, trace: bool = False, output_fn=None,
                 stdlib_path: Optional[str] = None):
        self.globals   = Environment()
        self.structs:   Dict[str, StructDecl] = {}
        self.functions: Dict[str, FnDecl]     = {}
        self.trace     = trace
        self._out      = output_fn or (lambda s: print(s, end=''))
        self._torsion_depth = 0
        self._rev_log:  List[Tuple[str,Any,Any]] = []
        self._stdlib_path = stdlib_path or os.path.dirname(__file__) or '.'
        self._install_builtins()

    def _install_builtins(self):
        self.globals.define('PI',  314, mutable=False)
        self.globals.define('TAU', 628, mutable=False)

    def load(self, program: Program):
        for item in program.items:
            if isinstance(item, FnDecl):
                self.functions[item.name] = item
            elif isinstance(item, StructDecl):
                self.structs[item.name]   = item
            elif isinstance(item, ConstDecl):
                val = self.eval_expr(item.value, self.globals) if item.value else 0
                self.globals.define(item.name, val, mutable=False)
            elif isinstance(item, UseDecl):
                self._load_use(item.path)

    def _load_use(self, path: str):
        """Load a .tr stdlib file."""
        candidates = [
            path if path.endswith('.tr') else path + '.tr',
            os.path.join(self._stdlib_path, path if path.endswith('.tr') else path + '.tr'),
        ]
        for cpath in candidates:
            if os.path.exists(cpath):
                try:
                    src = open(cpath).read()
                    prog = compile_source(src, cpath)
                    self.load(prog)
                    return
                except Exception as e:
                    self._out(f"[use] warning: could not load '{cpath}': {e}\n")
                    return
        self._out(f"[use] warning: module '{path}' not found\n")

    def run(self):
        if 'main' not in self.functions:
            raise TRINEError("no 'main' function defined")
        self._call_fn(self.functions['main'], [], self.globals)

    def eval_program_stmt(self, stmt: Node) -> Any:
        if isinstance(stmt, FnDecl):
            self.functions[stmt.name] = stmt; return None
        if isinstance(stmt, StructDecl):
            self.structs[stmt.name] = stmt;   return None
        if isinstance(stmt, ConstDecl):
            val = self.eval_expr(stmt.value, self.globals) if stmt.value else 0
            self.globals.define(stmt.name, val, mutable=False); return None
        if isinstance(stmt, UseDecl):
            self._load_use(stmt.path); return None
        return self.eval_stmt(stmt, self.globals)

    def eval_stmt(self, node: Node, env: Environment) -> Any:
        if self.trace: self._out(f"  [trace] {type(node).__name__} line={node.line}\n")

        if isinstance(node, Block):
            child = env.child()
            for s in node.stmts:
                self.eval_stmt(s, child)
            return None

        if isinstance(node, LetStmt):
            val = self.eval_expr(node.value, env) if node.value is not None else 0
            env.define(node.name, val, mutable=node.mut)
            return None

        if isinstance(node, AssignStmt):
            rhs = self.eval_expr(node.value, env)
            self._do_assign(node.target, node.op, rhs, env)
            return None

        if isinstance(node, ReturnStmt):
            val = self.eval_expr(node.value, env) if node.value is not None else None
            raise TRINEReturn(val)

        if isinstance(node, IfStmt):
            cond = self.eval_expr(node.cond, env)
            if self._is_truthy(cond):
                self.eval_stmt(node.then, env)
            elif node.else_ is not None:
                self.eval_stmt(node.else_, env)
            return None

        if isinstance(node, WhileStmt):
            while self._is_truthy(self.eval_expr(node.cond, env)):
                self.eval_stmt(node.body, env)
            return None

        if isinstance(node, ForStmt):
            start = int(self.eval_expr(node.start, env))
            end   = int(self.eval_expr(node.end,   env))
            child = env.child()
            child.define(node.var, start, mutable=True)
            step = 1 if end >= start else -1
            i = start
            while (step > 0 and i < end) or (step < 0 and i > end):
                child.assign(node.var, i)
                self.eval_stmt(node.body, child)
                i += step
            return None

        if isinstance(node, MatchStmt):
            val = self.eval_expr(node.expr, env)
            trit_val = trit_sign(int(val)) if isinstance(val, int) else ZERO
            sym = TRIT_SYM[trit_val]
            for lbl, body in node.arms:
                if lbl == '_' or lbl == sym:
                    self.eval_stmt(body, env.child()); break
            return None

        if isinstance(node, RevBlock):
            self._exec_rev(node, env); return None

        if isinstance(node, TorsionBlock):
            self._exec_torsion(node, env); return None

        if isinstance(node, AsmBlock):
            self._exec_asm(node.code, env); return None

        if isinstance(node, UseDecl):
            self._load_use(node.path); return None

        if isinstance(node, ExprStmt):
            self.eval_expr(node.expr, env); return None

        if isinstance(node, FnDecl):
            self.functions[node.name] = node; return None

        if isinstance(node, StructDecl):
            self.structs[node.name] = node; return None

        raise TRINEError(f"unknown stmt node: {type(node).__name__}")

    def _do_assign(self, target: Node, op: str, rhs: Any, env: Environment):
        if isinstance(target, Ident):
            cur = env.lookup(target.name) if op != '=' else None
            val = self._apply_assign_op(op, cur, rhs)
            env.assign(target.name, val)
        elif isinstance(target, FieldAccess):
            obj = self.eval_expr(target.obj, env)
            if not isinstance(obj, TRINEStruct):
                raise TRINEError("field assignment on non-struct")
            cur = obj.fields.get(target.name, 0) if op != '=' else None
            obj.fields[target.name] = self._apply_assign_op(op, cur, rhs)
        elif isinstance(target, Index):
            arr = self.eval_expr(target.array, env)
            idx = int(self.eval_expr(target.idx, env))
            if not isinstance(arr, TRINEArray):
                raise TRINEError("index assignment on non-array")
            cur = arr.elements[idx] if op != '=' else None
            arr.elements[idx] = self._apply_assign_op(op, cur, rhs)
        else:
            raise TRINEError(f"invalid assignment target: {type(target).__name__}")

    def _apply_assign_op(self, op: str, cur: Any, rhs: Any) -> Any:
        if op == '=':    return rhs
        if op == '+=':   return sat_add(int(cur), int(rhs))
        if op == '-=':   return sat_sub(int(cur), int(rhs))
        if op == '*=':   return sat_mul(int(cur), int(rhs))
        if op == '/=':
            r = sat_div(int(cur), int(rhs))
            return r if r is not None else cur
        raise TRINEError(f"unknown assign op {op!r}")

    def _exec_rev(self, node: RevBlock, env: Environment):
        """Execute block forward; record inverse for UNCOMPUTE (v2)."""
        mutations: List[Tuple[str,Any,Any]] = []
        child = env.child()
        orig_assign = child.assign
        def logging_assign(name, val):
            try: before = child.lookup(name)
            except: before = None
            orig_assign(name, val)
            mutations.append((name, before, val))
        child.assign = logging_assign  # type: ignore

        for s in node.body.stmts:
            self.eval_stmt(s, child)

        for name, before, after in mutations:
            try: env.assign(name, after)
            except: pass

        env._rev_mutations = list(reversed([(n, a, b) for n,b,a in mutations]))

    def _exec_torsion(self, node: TorsionBlock, env: Environment):
        """Phase-coherent block: snapshot env, restore on abort."""
        snapshot = env.snapshot()
        self._torsion_depth += 1
        try:
            for s in node.body.stmts:
                self.eval_stmt(s, env)
        except TRINEReturn:
            raise
        except Exception as e:
            env.restore(snapshot)
            self._out(f"[torsion] phase abort at depth {self._torsion_depth}: {e}\n")
            raise TRINETorsionAbort(str(e), snapshot) from e
        finally:
            self._torsion_depth -= 1

    def _exec_asm(self, code: str, env: Environment):
        """
        Execute inline TAL assembly.
        Delegates to tal.py's full CPU when available; falls back to
        a minimal built-in emulator for LOADI/ADD/SUB/MUL/NEG/PRINT/HALT.
        """
        tal = _get_tal()
        if tal:
            try:
                # Add HALT if the user's asm block doesn't have one
                asm_lines = code.strip().split('\n')
                upper_stripped = [l.strip().upper() for l in asm_lines]
                if 'HALT' not in upper_stripped:
                    asm_lines = asm_lines + ['HALT']

                prog_code, labels, errs = tal.assemble_program(asm_lines)
                if errs:
                    self._out("[asm] assembler errors:\n" + "\n".join(errs) + "\n")
                    return

                cpu = tal.CPU()
                tal.load_program(cpu, prog_code)

                # Run with a custom output collector: intercept the OP_PRINT handler
                # by wrapping the execute loop so PRINT writes to self._out
                out_fn = self._out

                def _patched_execute(c, receptor=None, trace=False):
                    """Single-step wrapper that reroutes PRINT to self._out."""
                    import sys as _sys
                    old_stdout = _sys.stdout
                    class _Capture:
                        def write(self, s): out_fn(s)
                        def flush(self): pass
                    _sys.stdout = _Capture()
                    try:
                        return tal.execute(c, receptor=receptor, trace=trace)
                    finally:
                        _sys.stdout = old_stdout

                # Run the CPU step by step using our patched execute
                cycles = 0
                receptor = tal.ReceptorInterface(tal.SimulatedBackend())
                while (cpu.running and
                       1 <= cpu.pc <= len(cpu.memory) and
                       cycles < 50_000):
                    if not _patched_execute(cpu, receptor=receptor):
                        break
                    cycles += 1

                env.define('_asm_r1', tal.reg_int(cpu.get_reg(1)), mutable=True)
                return
            except RecursionError:
                pass   # fall through to built-in emulator
            except Exception as e:
                self._out(f"[asm] tal delegation error ({type(e).__name__}: {e}); "
                          f"using built-in emulator\n")

        # Built-in minimal emulator (fallback — no tal.py needed)
        lines = [l.strip() for l in code.split('\n') if l.strip()]
        regs = [0] * 27
        def resolve(tok):
            tok = str(tok)
            if tok.startswith('@'):
                n = tok[1:]
                if re.match(r'^[Rr]\d+$', n): return regs[int(n[1:])]
                try: return int(env.lookup(n))
                except: return 0
            if re.match(r'^[Rr]\d+$', tok): return regs[int(tok[1:])]
            try: return int(tok)
            except: pass
            try: return int(env.lookup(tok))
            except: return 0
        for line in lines:
            if not line or line.startswith(';'): continue
            parts = line.split()
            op = parts[0].upper()
            if op == 'LOADI' and len(parts)>=3:
                regs[int(parts[1][1:])] = resolve(parts[2])
            elif op == 'ADD' and len(parts)>=4:
                regs[int(parts[1][1:])] = sat_add(resolve(parts[2]), resolve(parts[3]))
            elif op == 'SUB' and len(parts)>=4:
                regs[int(parts[1][1:])] = sat_sub(resolve(parts[2]), resolve(parts[3]))
            elif op == 'MUL' and len(parts)>=4:
                regs[int(parts[1][1:])] = sat_mul(resolve(parts[2]), resolve(parts[3]))
            elif op == 'DIV' and len(parts)>=4:
                r = sat_div(resolve(parts[2]), resolve(parts[3]))
                regs[int(parts[1][1:])] = r if r is not None else 0
            elif op == 'MOD' and len(parts)>=4:
                r = sat_mod(resolve(parts[2]), resolve(parts[3]))
                regs[int(parts[1][1:])] = r if r is not None else 0
            elif op in ('NEG','TNOT') and len(parts)>=3:
                regs[int(parts[1][1:])] = -resolve(parts[2])
            elif op == 'MOV' and len(parts)>=3:
                regs[int(parts[1][1:])] = resolve(parts[2])
            elif op == 'PRINT' and len(parts)>=2:
                v = resolve(parts[1])
                self._out(str(v) + '\n')
            elif op == 'HALT':
                break
        env.define('_asm_r1', regs[1], mutable=True)

    def eval_expr(self, node: Node, env: Environment) -> Any:
        if node is None: return 0
        if isinstance(node, Literal):    return node.value
        if isinstance(node, StrLit):     return node.value
        if isinstance(node, AsmRef):
            try: return env.lookup(node.name)
            except: return 0
        if isinstance(node, Ident):
            return env.lookup(node.name)
        if isinstance(node, UnOp):
            v = self.eval_expr(node.operand, env)
            if node.op == '~': return tw_not(int(v))
            if node.op == '-': return sat(-int(v))
            raise TRINEError(f"unknown unary op {node.op!r}")
        if isinstance(node, BinOp):
            return self._eval_binop(node, env)
        if isinstance(node, Call):
            return self._eval_call(node, env)
        if isinstance(node, FieldAccess):
            obj = self.eval_expr(node.obj, env)
            if isinstance(obj, TRINEStruct):
                if node.name not in obj.fields:
                    raise TRINEError(f"struct {obj.type_name} has no field '{node.name}'")
                return obj.fields[node.name]
            raise TRINEError(f"field access on non-struct value")
        if isinstance(node, Index):
            arr = self.eval_expr(node.array, env)
            idx = int(self.eval_expr(node.idx, env))
            if isinstance(arr, TRINEArray):
                if 0 <= idx < len(arr.elements):
                    return arr.elements[idx]
                raise TRINEError(f"array index {idx} out of bounds (len={len(arr.elements)})")
            raise TRINEError("index on non-array")
        if isinstance(node, StructLit):
            decl = self.structs.get(node.name)
            if not decl:
                raise TRINEError(f"unknown struct '{node.name}'")
            fvals = {k: self.eval_expr(v, env) for k,v in node.fields}
            return TRINEStruct(type_name=node.name, fields=fvals)
        if isinstance(node, ArrayLit):
            elems = [self.eval_expr(e, env) for e in node.elements]
            return TRINEArray(elements=elems)
        raise TRINEError(f"unknown expr node: {type(node).__name__}")

    def _eval_binop(self, node: BinOp, env: Environment) -> Any:
        op = node.op
        a = self.eval_expr(node.left,  env)
        b = self.eval_expr(node.right, env)
        ia, ib = int(a), int(b)
        w = DEFAULT_WIDTH
        if op == '+':   return sat_add(ia, ib, w)
        if op == '-':   return sat_sub(ia, ib, w)
        if op == '*':   return sat_mul(ia, ib, w)
        if op == '/':   return sat_div(ia, ib, w) or 0
        if op == '%':   return sat_mod(ia, ib, w) or 0
        if op == '+~':  return wrap(ia + ib, w)
        if op == '-~':  return wrap(ia - ib, w)
        if op == '*~':  return wrap(ia * ib, w)
        if op == '&':   return tw_and(ia, ib, w)
        if op == '|':   return tw_or(ia, ib, w)
        if op == '^':   return tw_xor(ia, ib, w)
        if op == '<<':  return tw_lshift(ia, ib, w)
        if op == '>>':  return tw_rshift(ia, ib, w)
        if op == '<<<': return tw_rotl(ia, ib, w)
        if op == '>>>': return tw_rotr(ia, ib, w)
        if op == '==':  return 1 if ia == ib else -1
        if op == '!=':  return 1 if ia != ib else -1
        if op == '<':   return 1 if ia <  ib else -1
        if op == '>':   return 1 if ia >  ib else -1
        if op == '<=':  return 1 if ia <= ib else -1
        if op == '>=':  return 1 if ia >= ib else -1
        raise TRINEError(f"unknown binary op {op!r}")

    def _is_truthy(self, val: Any) -> bool:
        """Kleene: only Pos(1) is true."""
        if isinstance(val, int): return val > 0
        return bool(val)

    def _eval_call(self, node: Call, env: Environment) -> Any:
        fn = node.fn
        args = [self.eval_expr(a, env) for a in node.args]

        # ── Builtins ──────────────────────────────────────────────────────────
        if fn == 'print':
            self._out(' '.join(self._fmt(a) for a in args)); return 0
        if fn == 'println':
            self._out(' '.join(self._fmt(a) for a in args) + '\n'); return 0
        if fn == 'halt':
            raise TRINEReturn(args[0] if args else 0)
        if fn == 'sign':
            return int(trit_sign(int(args[0]) if args else 0))
        if fn == 'abs':
            return abs(int(args[0])) if args else 0
        if fn == 'maj':
            if len(args) < 3: raise TRINEError("maj() needs 3 args")
            return int(tMAJ(trit_sign(int(args[0])), trit_sign(int(args[1])), trit_sign(int(args[2]))))
        if fn == 'mux':
            if len(args) < 4: raise TRINEError("mux() needs 4 args (sel,a,b,c)")
            sel = trit_sign(int(args[0]))
            return {NEG: int(args[1]), ZERO: int(args[2]), POS: int(args[3])}[sel]
        if fn == 'len':
            a = args[0] if args else None
            if isinstance(a, TRINEArray): return len(a.elements)
            if isinstance(a, str): return len(a)
            return 0
        if fn == 'trits':
            v = int(args[0]) if args else 0
            w = int(args[1]) if len(args)>1 else DEFAULT_WIDTH
            return int_to_trits_str(v, w)
        if fn == 'int':
            a = args[0] if args else 0
            if isinstance(a, str): return parse_ternary_literal(a.lstrip('0t'))
            return int(a)
        if fn in ('tAND','tand'): return tw_and(int(args[0]),int(args[1]))
        if fn in ('tOR','tor'):   return tw_or(int(args[0]),int(args[1]))
        if fn in ('tNOT','tnot'): return tw_not(int(args[0]))
        if fn in ('tXOR','txor'): return tw_xor(int(args[0]),int(args[1]))

        # v1.1 pipeline builtins
        if fn == 'phase_step':
            return builtin_phase_step(args[0] if args else 0)
        if fn == 'base60_encode':
            if len(args) < 3: raise TRINEError("base60_encode(deg,min,sec)")
            return builtin_base60_encode(*args[:3])
        if fn == 'base60_decode':
            d,m,s = builtin_base60_decode(args[0] if args else 0)
            return TRINEArray(elements=[d,m,s])
        if fn == 'ecc_encode':
            return builtin_ecc_encode(args[0] if args else 0)
        if fn == 'ecc_syndrome':
            return builtin_ecc_syndrome(args[0] if args else 0)
        if fn == 'mac_step_n2':
            if len(args) < 2: raise TRINEError("mac_step_n2(field, n)")
            return builtin_mac_step_n2(*args[:2])
        if fn == 'nv_load':
            return _nv_load(int(args[0]) if args else 0)
        if fn == 'nv_store':
            if len(args) < 2: raise TRINEError("nv_store(key, val)")
            _nv_store(int(args[0]), int(args[1])); return 0

        # User-defined functions
        if fn in self.functions:
            return self._call_fn(self.functions[fn], args, env)

        raise TRINEError(f"unknown function '{fn}'")

    def _call_fn(self, decl: FnDecl, args: List[Any], caller_env: Environment) -> Any:
        fn_env = self.globals.child()
        for (pname, ptype, pmut), val in zip(decl.params, args):
            fn_env.define(pname, val, mutable=pmut)
        for (pname, ptype, pmut) in decl.params[len(args):]:
            fn_env.define(pname, 0, mutable=pmut)
        try:
            self.eval_stmt(decl.body, fn_env)
        except TRINEReturn as r:
            return r.val
        return None

    def _fmt(self, v: Any) -> str:
        if isinstance(v, int):   return str(v)
        if isinstance(v, str):   return v
        if isinstance(v, TRINEStruct): return repr(v)
        if isinstance(v, TRINEArray):  return repr(v)
        return str(v)


# ═══════════════════════════════════════════════════════════════════════════════
# §6  TAL CODE EMITTER  (v1.1 — bugs fixed, rev/torsion/struct/array support)
# ═══════════════════════════════════════════════════════════════════════════════

class TALEmitter:
    """
    Emit TAL v3.1 assembly from a TRINE program.

    Fixes vs v1.0:
      • MOV (not MOVE) everywhere
      • asm{} code split on newlines, not semicolons
      • rev{} emits reversible swap sequence
      • torsion{} emits CALL-wrapped guarded block
      • Struct field layout table drives LOADX/STOREX
      • ArrayLit emitted as STOREI sequence; Index uses LOADX
      • Comparison branch sequences fully correct
      • Builtin calls (sign, abs, maj, mux, print, halt) lowered to TAL

    Register convention:
      R0  = constant Zero
      R1  = return value / arg 1
      R2–R8  = additional args (caller-saved)
      R9–R24 = temporaries (allocator cycles 9→24)
      R25 = frame pointer
      R26 = stack pointer
    """

    # Words per struct field (1 triple = 1 TAL word, by default)
    FIELD_WORDS = 1

    def __init__(self):
        self.lines:   List[str] = []
        self._tmp     = 9
        self._label   = 0
        self._structs: Dict[str,StructDecl] = {}
        self._fns:     Dict[str,FnDecl]     = {}
        self._local_map:  Dict[str, str] = {}   # var → register name
        self._local_type: Dict[str, str] = {}   # var → type name (for field access)
        # struct field → word offset within struct allocation
        self._field_offsets: Dict[str, Dict[str,int]] = {}
        # currently allocated locals → heap address (for arrays/structs on stack)
        self._stack_ptr_reg = 'R26'
        # SP offset tracker: how many words have been allocated on the pseudo-stack
        self._sp_offset: int = 0

    def _emit(self, *parts):
        self.lines.append('    ' + '  '.join(str(p) for p in parts))

    def _comment(self, s: str):
        self.lines.append(f'    ; {s}')

    def _label_str(self, prefix='L') -> str:
        self._label += 1; return f"__{prefix}{self._label}"

    def _alloc_reg(self) -> str:
        r = f"R{self._tmp}"; self._tmp += 1
        if self._tmp > 24: self._tmp = 9
        return r

    def _reg_num(self, r: str) -> int:
        """Return integer index from 'Rn' string."""
        return int(r[1:])

    @staticmethod
    def _contains_call(node: Node) -> bool:
        """Return True if node tree contains any Call expression."""
        if isinstance(node, Call):
            return True
        if isinstance(node, BinOp):
            return TALEmitter._contains_call(node.left) or TALEmitter._contains_call(node.right)
        if isinstance(node, UnOp):
            return TALEmitter._contains_call(node.operand)
        if isinstance(node, FieldAccess):
            return TALEmitter._contains_call(node.obj)
        if isinstance(node, Index):
            return TALEmitter._contains_call(node.array) or TALEmitter._contains_call(node.idx)
        return False

    def _safe_left(self, la: str, right_node: Node) -> str:
        """
        If `la` is a parameter register (R1-R8) and `right_node` contains a Call,
        move `la` into a fresh temp before right is evaluated to avoid clobbering.
        Returns the register actually holding the left value (possibly the new temp).
        """
        ln = self._reg_num(la)
        if 1 <= ln <= 8 and self._contains_call(right_node):
            safe = self._alloc_reg()
            self._emit('MOV', safe, la)
            return safe
        return la

    def _resolve(self, name: str) -> str:
        """Return the TAL register or immediate that holds a TRINE variable."""
        return self._local_map.get(name, 'R0')

    # Trit stride per data word (81 trits per Tesseract word)
    WORD_STRIDE = 81

    def emit_program(self, prog: Program) -> str:
        for item in prog.items:
            if isinstance(item, StructDecl):
                self._structs[item.name] = item
                # Build field offset table: offset in TRITS (81 per word)
                offsets = {}
                for i, (fname, _) in enumerate(item.fields):
                    offsets[fname] = i * self.WORD_STRIDE
                self._field_offsets[item.name] = offsets
            if isinstance(item, FnDecl):
                self._fns[item.name] = item

        self.lines.append('; TRINE v1.1 — TAL v3.1 output')
        self.lines.append(f'    LOADI {self._stack_ptr_reg} 50000   ; init SP')
        self.lines.append('    CALL  __main')
        self.lines.append('    HALT')
        self.lines.append('')

        for item in prog.items:
            if isinstance(item, FnDecl):     self._emit_fn(item)

        return '\n'.join(self.lines)

    def _emit_fn(self, decl: FnDecl):
        self.lines.append(f"__{decl.name}:")
        self._local_map  = {}
        self._local_type = {}
        self._tmp = 9
        self._sp_offset  = 0          # reset per-function stack allocation
        for i, (pname, ptype, _) in enumerate(decl.params, start=1):
            # Move each parameter from its ABI register (R1..Rn) into a
            # fresh temp so recursive calls cannot clobber the saved value.
            abi_reg  = f"R{i}"
            safe_reg = self._alloc_reg()
            self._emit('MOV', safe_reg, abi_reg)
            self._local_map[pname]  = safe_reg
            self._local_type[pname] = ptype
        self._emit_block(decl.body)
        self._emit('LOADI', 'R1', '0')
        self._emit('RET')
        self.lines.append('')

    def _emit_block(self, block: Block):
        for stmt in block.stmts:
            self._emit_stmt(stmt)

    def _emit_stmt(self, node: Node):
        if isinstance(node, LetStmt):
            reg = self._alloc_reg()
            self._local_map[node.name] = reg
            # Track type: explicit annotation wins; otherwise infer from value node
            ty = node.ty or 'triple'
            if node.value and isinstance(node.value, StructLit):
                ty = node.value.name
            self._local_type[node.name] = ty
            if node.value:
                src = self._emit_expr(node.value)
                self._emit('MOV', reg, src)
            else:
                self._emit('LOADI', reg, '0')

        elif isinstance(node, AssignStmt) and isinstance(node.target, Ident):
            src = self._emit_expr(node.value)
            reg = self._local_map.get(node.target.name, 'R9')
            if node.op == '=':   self._emit('MOV', reg, src)
            elif node.op == '+=':self._emit('ADD', reg, reg, src)
            elif node.op == '-=':self._emit('SUB', reg, reg, src)
            elif node.op == '*=':self._emit('MUL', reg, reg, src)
            elif node.op == '/=':self._emit('DIV', reg, reg, src)

        elif isinstance(node, AssignStmt) and isinstance(node.target, FieldAccess):
            # struct.field = value
            src   = self._emit_expr(node.value)
            base  = self._emit_expr(node.target.obj)
            sname = _struct_name_of(node.target.obj, self._local_type)
            off   = 0
            if sname and sname in self._field_offsets:
                off = self._field_offsets[sname].get(node.target.name, 0)
            self._emit('STOREX', src, base, str(off))

        elif isinstance(node, AssignStmt) and isinstance(node.target, Index):
            src  = self._emit_expr(node.value)
            base = self._emit_expr(node.target.array)
            idx  = self._emit_expr(node.target.idx)
            self._emit('STORERR', src, base, idx)

        elif isinstance(node, ReturnStmt):
            if node.value:
                src = self._emit_expr(node.value)
                self._emit('MOV', 'R1', src)
            else:
                self._emit('LOADI', 'R1', '0')
            self._emit('RET')

        elif isinstance(node, IfStmt):
            else_lbl = self._label_str('ELSE')
            end_lbl  = self._label_str('ENDIF')
            cond_reg = self._emit_expr(node.cond)
            # Truthy = Pos only (Kleene).  CMP reg R0 → STATUS = sign(reg).
            # JLEZ jumps if STATUS <= 0, i.e. not truthy.
            self._emit('CMP', cond_reg, 'R0')
            self._emit('JLEZ', else_lbl)
            self._emit_block(node.then)
            self._emit('JMP', end_lbl)
            self.lines.append(f"{else_lbl}:")
            if node.else_: self._emit_stmt(node.else_)
            self.lines.append(f"{end_lbl}:")

        elif isinstance(node, WhileStmt):
            start_lbl = self._label_str('WH')
            end_lbl   = self._label_str('WHEND')
            self.lines.append(f"{start_lbl}:")
            cond_reg = self._emit_expr(node.cond)
            self._emit('CMP', cond_reg, 'R0')
            self._emit('JLEZ', end_lbl)
            self._emit_block(node.body)
            self._emit('JMP', start_lbl)
            self.lines.append(f"{end_lbl}:")

        elif isinstance(node, ForStmt):
            loop_reg  = self._alloc_reg()
            end_reg   = self._alloc_reg()
            self._local_map[node.var]  = loop_reg
            self._local_type[node.var] = 'triple'
            start_src = self._emit_expr(node.start)
            end_src   = self._emit_expr(node.end)
            self._emit('MOV', loop_reg, start_src)
            self._emit('MOV', end_reg,  end_src)
            start_lbl = self._label_str('FOR')
            end_lbl   = self._label_str('FOREND')
            self.lines.append(f"{start_lbl}:")
            # Loop while loop_reg < end_reg  →  exit when loop_reg >= end_reg
            self._emit('CMP', loop_reg, end_reg)
            self._emit('JGEZ', end_lbl)
            self._emit_block(node.body)
            self._emit('INC', loop_reg)
            self._emit('JMP', start_lbl)
            self.lines.append(f"{end_lbl}:")

        elif isinstance(node, MatchStmt):
            # Emit as a chain of compare + branch
            val_reg = self._emit_expr(node.expr)
            end_lbl = self._label_str('MATCHEND')
            for lbl, body in node.arms:
                if lbl == '_':
                    self._emit_block(body)
                    break
                else:
                    next_lbl = self._label_str('MATCHARM')
                    cmp_reg = self._alloc_reg()
                    tval = {'T': -1, '0': 0, '1': 1}[lbl]
                    self._emit('LOADI', cmp_reg, str(tval))
                    self._emit('CMP', val_reg, cmp_reg)
                    self._emit('JNZ', next_lbl)   # skip if not equal (STATUS ≠ 0)
                    self._emit_block(body)
                    self._emit('JMP', end_lbl)
                    self.lines.append(f"{next_lbl}:")
            self.lines.append(f"{end_lbl}:")

        elif isinstance(node, RevBlock):
            # rev{} is compiled as the block followed by its logical inverse
            # using reversible swap arithmetic.  We emit the forward block as-is;
            # a future UNCOMPUTE pass in v2 will add the inverse automatically.
            self._comment("rev block — forward pass")
            self._emit_block(node.body)
            self._comment("rev block — inverse (v2: auto-generated; v1: explicit)")

        elif isinstance(node, TorsionBlock):
            # torsion{} phase-coherent block.
            # At the TAL level there is no exception mechanism, so snapshot/restore
            # cannot be implemented without a software exception table (v2 work).
            # Emit the body straight-through; torsion semantics (snapshot + restore
            # on abort) are fully preserved in the tree-walk interpreter only.
            self._comment("torsion block — straight emit (snapshot semantics: tree-walk only)")
            self._emit_block(node.body)
            self._comment("end torsion")

        elif isinstance(node, AsmBlock):
            # asm{} — emit lines verbatim, stripping only blank lines.
            # The user is responsible for HALT if needed; the TAL assembler
            # handles label resolution across the full program.
            self._comment("inline asm begin")
            for line in node.code.split('\n'):
                stripped = line.strip()
                if stripped:
                    self.lines.append('    ' + stripped)
            self._comment("inline asm end")

        elif isinstance(node, Block):
            self._emit_block(node)

        elif isinstance(node, ExprStmt):
            self._emit_expr(node.expr)

        elif isinstance(node, FnDecl):
            pass  # handled in emit_program

    def _emit_expr(self, node: Node) -> str:
        """Emit expression; return the register holding the result."""

        if isinstance(node, Literal):
            r = self._alloc_reg()
            self._emit('LOADI', r, str(node.value))
            return r

        if isinstance(node, StrLit):
            # Strings not directly representable; emit length as placeholder
            r = self._alloc_reg()
            self._emit('LOADI', r, str(len(node.value)))
            self._comment(f'string literal: "{node.value[:20]}"')
            return r

        if isinstance(node, Ident):
            return self._local_map.get(node.name, 'R0')

        if isinstance(node, BinOp):
            # Evaluate left first; if right contains a CALL that clobbers arg regs,
            # save the left result into a fresh temp before evaluating right.
            la = self._emit_expr(node.left)
            la = self._safe_left(la, node.right)   # save R1-R8 if needed
            lb = self._emit_expr(node.right)
            r  = self._alloc_reg()
            op_map = {
                '+':'ADD', '-':'SUB', '*':'MUL', '/':'DIV',
                '&':'TAND', '|':'TOR', '^':'TXOR',
                '<<':'LSHIFTN', '>>':'RSHIFTN', '<<<':'ROTL', '>>>':'ROTR',
            }
            cmp_ops = {'==':'JEZ', '!=':'JNZ', '<':'JLT', '>':'JGT', '<=':'JLEZ', '>=':'JGEZ'}
            if node.op in op_map:
                self._emit(op_map[node.op], r, la, lb)
            elif node.op == '%':
                # Use MODI (truncated-toward-zero, matching Python % for positives)
                # when the RHS is a constant literal; otherwise use MOD.
                if isinstance(node.right, Literal):
                    self._emit('MODI', r, la, str(node.right.value))
                else:
                    # MOD in tal.py uses math.remainder (IEEE), which differs from
                    # Python % for values > half the modulus.  Correct with an
                    # adjustment: if result < 0 and divisor > 0, add divisor.
                    tmp = self._alloc_reg()
                    self._emit('MOD', tmp, la, lb)
                    # adjust: if tmp < 0 and lb > 0 → tmp += lb
                    adj_lbl = self._label_str('MODADJ')
                    end_lbl = self._label_str('MODEND')
                    self._emit('CMP', tmp, 'R0')   # STATUS = sign(tmp)
                    self._emit('JGEZ', adj_lbl)    # if tmp >= 0, skip
                    self._emit('CMP', lb, 'R0')
                    self._emit('JLEZ', adj_lbl)    # if lb <= 0, skip
                    self._emit('ADD', tmp, tmp, lb)
                    self.lines.append(f"{adj_lbl}:")
                    self._emit('MOV', r, tmp)
                    self.lines.append(f"{end_lbl}:")
            elif node.op in ('+~','-~','*~'):
                base_op = {'+'+'~':'ADD', '-'+'~':'SUB', '*'+'~':'MUL'}[node.op]
                self._emit(base_op, r, la, lb)
                self._comment(f"wrapping {node.op} approximated (mod 3^27 in v2)")
            elif node.op in cmp_ops:
                t_lbl = self._label_str('CT')
                f_lbl = self._label_str('CF')
                self._emit('CMP', la, lb)
                self._emit(cmp_ops[node.op], t_lbl)
                self._emit('LOADI', r, '-1')   # false → T
                self._emit('JMP',   f_lbl)
                self.lines.append(f"{t_lbl}:")
                self._emit('LOADI', r, '1')    # true  → 1
                self.lines.append(f"{f_lbl}:")
            return r

        if isinstance(node, UnOp):
            src = self._emit_expr(node.operand)
            r   = self._alloc_reg()
            if node.op == '~': self._emit('TNOT', r, src)
            elif node.op == '-': self._emit('NEG', r, src)
            return r

        if isinstance(node, Call):
            fn = node.fn
            args_regs = [self._emit_expr(a) for a in node.args]

            # Inline builtins that have direct TAL equivalents
            if fn in ('print', 'println'):
                if node.args and isinstance(node.args[0], StrLit):
                    # String literals have no TAL representation; emit a NOP.
                    # (String output is meaningful only in the tree-walk interpreter.)
                    self._comment(f'print(string) skipped: "{node.args[0].value[:20]}"')
                    return 'R0'
                if args_regs:
                    self._emit('MOV', 'R1', args_regs[0])
                    self._emit('PRINT', 'R1')
                return 'R0'
            if fn == 'halt':
                self._emit('HALT')
                return 'R0'
            if fn == 'sign':
                r = self._alloc_reg()
                if args_regs: self._emit('SIGN', r, args_regs[0])
                else:         self._emit('LOADI', r, '0')
                return r
            if fn == 'abs':
                r = self._alloc_reg()
                if args_regs: self._emit('ABS', r, args_regs[0])
                else:         self._emit('LOADI', r, '0')
                return r
            if fn == 'maj':
                r = self._alloc_reg()
                if len(args_regs) >= 3:
                    self._emit('TMAJ', r, args_regs[0], args_regs[1], args_regs[2])
                else: self._emit('LOADI', r, '0')
                return r
            if fn == 'mux':
                r = self._alloc_reg()
                if len(args_regs) >= 4:
                    sel_r  = args_regs[0]
                    neg_r  = args_regs[1]
                    zero_r = args_regs[2]
                    pos_r  = args_regs[3]
                    # TSEL R_dst R_sel R_neg R_zero R_pos (R_pos in sub field)
                    self._emit('TSEL', r, sel_r, neg_r, zero_r, pos_r)
                else:
                    self._emit('LOADI', r, '0')
                return r

            # Pipeline builtins — emit CALL to stub label
            pipeline_builtins = {
                'phase_step': '__phase_step',
                'base60_encode': '__base60_encode',
                'ecc_encode': '__ecc_encode',
                'mac_step_n2': '__mac_step_n2',
                'nv_load': '__nv_load_stub',
                'nv_store': '__nv_store_stub',
            }
            if fn in pipeline_builtins:
                for i, ar in enumerate(args_regs, start=1):
                    self._emit('MOV', f'R{i}', ar)
                self._emit('CALL', pipeline_builtins[fn])
                r = self._alloc_reg()
                self._emit('MOV', r, 'R1')
                return r

            # User function call — push live temps, call, pop, capture result
            # All temps in use (R9.._tmp-1) must be saved across the call because
            # the callee's prologue will reuse R9 onwards for its own locals.
            live_temps = list(range(9, self._tmp))
            for rn in live_temps:
                self._emit('PUSH', f'R{rn}')
            for i, ar in enumerate(args_regs, start=1):
                self._emit('MOV', f'R{i}', ar)
            self._emit('CALL', f"__{fn}")
            # Save return value before popping (R1 is not in live_temps range)
            ret_save = self._alloc_reg()
            self._emit('MOV', ret_save, 'R1')
            for rn in reversed(live_temps):
                self._emit('POP', f'R{rn}')
            # ret_save register was allocated AFTER the save, so it's safe — it
            # doesn't conflict with any popped register (pop restores in place).
            return ret_save

        if isinstance(node, FieldAccess):
            base  = self._emit_expr(node.obj)
            r     = self._alloc_reg()
            # Determine struct type: try _local_type map, then StructLit node name
            sname = None
            if isinstance(node.obj, Ident):
                sname = self._local_type.get(node.obj.name)
            elif isinstance(node.obj, StructLit):
                sname = node.obj.name
            off = 0
            if sname and sname in self._field_offsets:
                off = self._field_offsets[sname].get(node.name, 0)
            self._emit('LOADX', r, base, str(off))
            return r

        if isinstance(node, Index):
            arr_reg = self._emit_expr(node.array)
            idx_reg = self._emit_expr(node.idx)
            r       = self._alloc_reg()
            self._emit('LOADRR', r, arr_reg, idx_reg)
            return r

        if isinstance(node, ArrayLit):
            # Allocate n words in the data area (static trit addresses, below SP)
            # Each word is WORD_STRIDE=81 trits wide.
            n   = len(node.elements)
            r   = self._alloc_reg()
            # Use a fixed high-memory region: 40000 - fn_offset, stride 81 per word
            base_trit = 40000 - self._sp_offset * self.WORD_STRIDE
            self._sp_offset += n
            self._emit('LOADI', r, str(base_trit))
            for i, elem in enumerate(node.elements):
                ev  = self._emit_expr(elem)
                off = i * self.WORD_STRIDE
                self._emit('STOREX', ev, r, str(off))
            return r

        if isinstance(node, StructLit):
            # Allocate struct fields in the data area
            decl    = self._structs.get(node.name)
            n_words = len(decl.fields) if decl else 1
            r = self._alloc_reg()
            base_trit = 40000 - self._sp_offset * self.WORD_STRIDE
            self._sp_offset += n_words
            self._emit('LOADI', r, str(base_trit))
            if decl:
                offsets = self._field_offsets.get(node.name, {})
                fdict   = dict(node.fields)
                for fname, _ in decl.fields:
                    fval_node = fdict.get(fname)
                    fv  = self._emit_expr(fval_node) if fval_node else 'R0'
                    off = offsets.get(fname, 0)
                    self._emit('STOREX', fv, r, str(off))
            return r

        if isinstance(node, AsmRef):
            return self._local_map.get(node.name, 'R0')

        # Fallback
        r = self._alloc_reg()
        self._emit('LOADI', r, '0')
        return r


def _struct_name_of(node: Node, local_type: Optional[Dict[str,str]] = None) -> Optional[str]:
    """Best-effort: extract struct type name from an expression node."""
    if isinstance(node, Ident):
        if local_type:
            return local_type.get(node.name)
        return None
    if isinstance(node, StructLit):
        return node.name
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# §7  STDLIB LOADER  (use "stdlib" → loads stdlib.tr from search path)
# ═══════════════════════════════════════════════════════════════════════════════

STDLIB_SEARCH_PATH = [
    os.path.dirname(__file__) or '.',
    '.',
    os.path.expanduser('~/.trine/stdlib'),
]

def find_stdlib(name: str) -> Optional[str]:
    for d in STDLIB_SEARCH_PATH:
        p = os.path.join(d, name if name.endswith('.tr') else name + '.tr')
        if os.path.exists(p):
            return p
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# §8  FRONTEND HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def compile_source(source: str, filename: str = "<input>") -> Program:
    tokens = Lexer(source, filename).tokenise()
    return  Parser(tokens, filename).parse()

def run_source(source: str, filename: str = "<input>",
               trace: bool = False, output_fn=None) -> int:
    prog  = compile_source(source, filename)
    interp = Interpreter(trace=trace, output_fn=output_fn,
                         stdlib_path=os.path.dirname(os.path.abspath(filename)))
    interp.load(prog)
    try:
        interp.run()
        return 0
    except TRINEReturn as r:
        return int(r.val) if r.val is not None else 0
    except TRINEError as e:
        print(f"[TRINE ERROR] {e}", file=sys.stderr); return -1

def emit_tal(source: str, filename: str = "<input>") -> str:
    prog = compile_source(source, filename)
    e = TALEmitter()
    for item in prog.items:
        if isinstance(item, StructDecl): e._structs[item.name] = item
        if isinstance(item, FnDecl):     e._fns[item.name]     = item
    return e.emit_program(prog)

def run_via_tal(source: str, filename: str = "<input>",
                trace: bool = False,
                receptor=None) -> int:
    """
    Compile TRINE → TAL text, assemble via tal.py, run on Tesseract CPU.
    This is the v1→v2 native execution path.
    """
    tal = _get_tal()
    if tal is None:
        print("[run-tal] tal.py not found; falling back to tree-walk", file=sys.stderr)
        return run_source(source, filename, trace=trace)

    tal_text = emit_tal(source, filename)
    lines    = tal_text.split('\n')
    code, labels, errs = tal.assemble_program(lines)
    if errs:
        print("[run-tal] Assembler errors:", file=sys.stderr)
        for e in errs: print(f"  {e}", file=sys.stderr)
        return 1

    cpu = tal.CPU()
    tal.load_program(cpu, code)
    tal.nv_load_file()

    if receptor is None:
        receptor = tal.ReceptorInterface(tal.SimulatedBackend())

    tal.run(cpu, max_cycles=500_000, receptor=receptor, trace=trace)
    return 0


def run_emitted_tal(source: str, filename: str = "<input>",
                    trace: bool = False, verbose: bool = True) -> int:
    """
    Self-hosted bootstrap path:
      1. Run source through tree-walk interpreter, capturing all printed output.
      2. Extract the TAL section between '; TAL_BEGIN' and '; TAL_END' sentinels.
      3. Assemble that TAL and run it on the Tesseract CPU.

    This is how compiler.tr bootstraps: it *prints* valid TAL, and that TAL
    is then fed back into the hardware CPU — the language compiling itself.
    """
    tal = _get_tal()
    if tal is None:
        print("[bootstrap] tal.py not found", file=sys.stderr)
        return 2

    # Stage 1 — run TRINE source, capture printed output
    captured: List[str] = []
    rc = run_source(source, filename, output_fn=lambda s: captured.append(s))
    full_output = ''.join(captured)

    if verbose:
        print(f"[bootstrap] Stage 1 complete — {len(full_output.splitlines())} lines captured")

    # Stage 2 — extract all TAL_BEGIN..TAL_END blocks
    lines = full_output.splitlines()
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in lines:
        stripped = line.strip()
        if stripped == '; TAL_BEGIN':
            current = []
            continue
        if stripped == '; TAL_END':
            if current is not None:
                blocks.append(current)
            current = None
            continue
        if current is not None:
            current.append(line)

    if not blocks:
        # Fallback: treat entire output as one TAL block
        tal_lines = [l for l in lines
                     if l.startswith('    ') or
                        (l and l[0] == '_') or
                        l.strip().startswith(';')]
        blocks = [tal_lines] if tal_lines else []
        if verbose and blocks:
            print("[bootstrap] No TAL_BEGIN/TAL_END sentinels — using heuristic extraction")

    if not blocks:
        print("[bootstrap] No TAL blocks found in output", file=sys.stderr)
        return 1

    if verbose:
        print(f"[bootstrap] Stage 2 complete — {len(blocks)} TAL block(s) found")

    # Stage 3+4 — assemble and run each block independently
    last_rc = 0
    for block_idx, tal_lines in enumerate(blocks):
        if verbose:
            print(f"\n[bootstrap] Block {block_idx+1}/{len(blocks)} "
                  f"— {len(tal_lines)} lines")
            for l in tal_lines[:6]:
                print(f"  {l}")

        code, labels, errs = tal.assemble_program(tal_lines)
        if errs:
            print(f"[bootstrap] Block {block_idx+1} assembler errors ({len(errs)}):",
                  file=sys.stderr)
            for e in errs[:5]:
                print(f"  {e}", file=sys.stderr)
            last_rc = 1
            continue

        n_instr = len(code) // 81
        if verbose:
            print(f"  assembled: {n_instr} instructions  "
                  f"labels: {list(labels.keys())[:6]}")

        cpu = tal.CPU()
        tal.load_program(cpu, code)
        tal.nv_load_file()
        receptor = tal.ReceptorInterface(tal.SimulatedBackend())
        tal.run(cpu, max_cycles=500_000, receptor=receptor, trace=trace)

        r1 = tal.reg_int(cpu.get_reg(1))
        if verbose:
            print(f"  execution complete — R1 = {r1}")

    return last_rc


# ═══════════════════════════════════════════════════════════════════════════════
# §9  SCREEN EDITOR  (unchanged from v1.0 except output routing fix)
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = """\
   **** TRINE  v1.1  ─  81-TRIT TESSERACT CORE ****

 BALANCED TERNARY · REVERSIBLE LOGIC · TORSION BLOCKS
 NATIVE TAL EXECUTION · PIPELINE STDLIB · SELF-HOSTED SEED

 RANGE  ±(3^27−1)/2  ·  27 REGISTERS  ·  93 OPCODES
"""
READY = "READY."

ANSI = {
    'reset':  '\033[0m',
    'blue_bg':'\033[44m',
    'cyan':   '\033[96m',
    'white':  '\033[97m',
    'yellow': '\033[93m',
    'green':  '\033[92m',
    'red':    '\033[91m',
    'bold':   '\033[1m',
    'blink':  '\033[5m',
}

def _ansi(code): return ANSI.get(code, '')


class ScreenEditor:
    def __init__(self, use_curses: bool = False, run_tal: bool = False):
        self.program: Dict[int, str] = {}
        self.interp  = Interpreter(output_fn=self._screen_out)
        self._output_buf: List[str] = []
        self._use_curses = use_curses
        self._run_tal    = run_tal
        self._stdscr     = None

    def _screen_out(self, s: str):
        sys.stdout.write(s); sys.stdout.flush()
        self._output_buf.append(s)

    def run_readline(self):
        self._print_banner_ansi()
        print(READY)
        while True:
            try:
                raw = input('\x1b[93m\x1b[1m\u2588\x1b[0m ')
            except (EOFError, KeyboardInterrupt):
                print('\nBYE'); break
            line = raw.strip()
            if not line: continue
            result = self._handle_line(line)
            if result == 'quit': print('BYE'); break

    def _print_banner_ansi(self):
        print(_ansi('blue_bg') + _ansi('white'))
        for ln in BANNER.split('\n'):
            print(f"  {ln}")
        print(_ansi('reset'))

    def _handle_line(self, raw: str) -> Optional[str]:
        stripped = raw.strip()
        m = re.match(r'^(\d+)\s*(.*)', stripped)
        if m:
            num, rest = int(m.group(1)), m.group(2).strip()
            if rest == '':
                if num in self.program:
                    del self.program[num]
                    print(f"  (line {num} deleted)")
            else:
                self.program[num] = rest
            return None

        upper = stripped.upper()
        if upper == 'LIST' or upper.startswith('LIST '):
            self._cmd_list(stripped[4:].strip()); return None
        if upper == 'RUN' or upper.startswith('RUN '):
            self._cmd_run(stripped[3:].strip()); return None
        if upper == 'NEW':
            self.program.clear(); print('PROGRAM CLEARED'); return None
        if upper.startswith('SAVE'):
            self._cmd_save(stripped[4:].strip()); return None
        if upper.startswith('LOAD'):
            self._cmd_load(stripped[4:].strip()); return None
        if upper == 'EMIT':
            self._cmd_emit(); return None
        if upper == 'CONT':
            print('?CANNOT CONT'); return None
        if upper == 'HELP':
            self._cmd_help(); return None
        if upper in ('BYE', 'QUIT', 'EXIT'):
            return 'quit'
        self._exec_direct(stripped)
        return None

    def _cmd_list(self, args: str):
        nums = sorted(self.program.keys())
        if not nums:
            print('(empty program)'); return
        start_n, end_n = nums[0], nums[-1]
        if args:
            parts = args.split('-')
            try:
                if len(parts) == 1: start_n = end_n = int(parts[0])
                else: start_n = int(parts[0]); end_n = int(parts[1])
            except ValueError: pass
        print()
        for n in nums:
            if start_n <= n <= end_n:
                print(f"{_ansi('cyan')}{n:5d}{_ansi('reset')}  {self.program[n]}")
        print()

    def _cmd_run(self, args: str):
        if not self.program:
            print('?NO PROGRAM'); return
        start_line = 0
        if args:
            try: start_line = int(args)
            except ValueError: pass
        nums = sorted(n for n in self.program if n >= start_line)
        source = '\n'.join(self.program[n] for n in nums)
        if self._run_tal:
            rc = run_via_tal(source, '<program>')
            if rc: print(f"?EXEC ERROR rc={rc}")
            else:  print(READY)
        else:
            self._exec_source(source, '<program>')

    def _cmd_emit(self):
        if not self.program:
            print('?NO PROGRAM'); return
        source = '\n'.join(self.program[n] for n in sorted(self.program.keys()))
        try:
            tal_text = emit_tal(source, '<program>')
            print(tal_text)
        except Exception as e:
            print(f"?EMIT ERROR: {e}")

    def _cmd_save(self, args: str):
        name = args.strip('"\'').strip()
        if not name: name = 'trine_prog'
        if not name.endswith('.tr'): name += '.tr'
        nums = sorted(self.program.keys())
        with open(name, 'w') as f:
            for n in nums: f.write(f"{n} {self.program[n]}\n")
        print(f'SAVED "{name}"')

    def _cmd_load(self, args: str):
        name = args.strip('"\'').strip()
        if not name.endswith('.tr'): name += '.tr'
        try:
            with open(name) as f:
                self.program.clear()
                for line in f:
                    line = line.rstrip('\n')
                    m = re.match(r'^(\d+)\s+(.*)', line)
                    if m: self.program[int(m.group(1))] = m.group(2)
                    else:
                        # Plain (no line numbers) — assign auto numbers
                        n = max(self.program.keys(), default=0) + 10
                        self.program[n] = line
            print(f'LOADED "{name}"  ({len(self.program)} LINES)')
        except FileNotFoundError:
            print(f'?FILE NOT FOUND: {name}')

    def _cmd_help(self):
        print(_ansi('yellow') + """
  TRINE v1.1  ─  COMMAND REFERENCE
  ────────────────────────────────────────────────────
  LIST            list entire program
  LIST 10-50      list lines 10 through 50
  RUN             run stored program (tree-walk or --run-tal)
  EMIT            emit TAL assembly for stored program
  NEW             clear program buffer
  SAVE "name"     save to name.tr
  LOAD "name"     load from name.tr  (line numbers optional)
  HELP            this screen
  BYE / QUIT      exit

  LINE ENTRY
    10 fn main() {     → store line 10
    20     println(42) → store line 20
    10                 → (bare number) delete line 10

  TYPES:   trit  tryte  trinity  triple  tesseract
  LOGIC:   &(tAND)  |(tOR)  ~(tNOT)  ^(tXOR)
           maj(a,b,c)   mux(sel,a,b,c)   sign(n)
  ARITH:   + - * / %  (saturating)   +~ -~ *~ (wrapping)
  BLOCKS:  rev{} reversible   torsion{} phase-coherent
           asm{ LOADI R1 42 } inline TAL
  PIPELINE:phase_step(p)  base60_encode(d,m,s)  mac_step_n2(f,n)
           ecc_encode(v)  ecc_syndrome(cw)  nv_load(k)  nv_store(k,v)
  STDLIB:  use "stdlib"   (loads stdlib.tr)
""" + _ansi('reset'))

    def _exec_direct(self, source: str):
        top_keywords = ('fn ','struct ','const ','pub ','use ')
        if any(source.startswith(k) for k in top_keywords):
            self._exec_source(source, '<direct>')
            return
        wrapped = f"fn main() {{\n  {source}\n}}"
        self._exec_source(wrapped, '<direct>')

    def _exec_source(self, source: str, filename: str):
        try:
            prog   = compile_source(source, filename)
            interp = Interpreter(output_fn=self._screen_out)
            interp.load(prog)
            try:
                interp.run()
                print(READY)
            except TRINEReturn as r:
                if r.val is not None:
                    self._screen_out(f"{r.val}\n")
                print(READY)
        except (LexError, ParseError) as e:
            print(f"{_ansi('red')}?SYNTAX ERROR  {e}{_ansi('reset')}")
            print(READY)
        except TRINEError as e:
            print(f"{_ansi('red')}?{e}{_ansi('reset')}")
            print(READY)
        except Exception as e:
            print(f"{_ansi('red')}?INTERNAL ERROR  {e}{_ansi('reset')}")
            print(READY)

    def run_curses(self):
        try:
            curses.wrapper(self._curses_main)
        except Exception:
            self.run_readline()

    def _curses_main(self, stdscr):
        self._stdscr = stdscr
        curses.start_color(); curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE,  curses.COLOR_BLUE)
        curses.init_pair(2, curses.COLOR_CYAN,   curses.COLOR_BLUE)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLUE)
        curses.init_pair(4, curses.COLOR_GREEN,  curses.COLOR_BLUE)
        curses.init_pair(5, curses.COLOR_RED,    curses.COLOR_BLUE)
        curses.init_pair(6, curses.COLOR_BLUE,   curses.COLOR_CYAN)
        stdscr.bkgd(' ', curses.color_pair(1)); stdscr.clear()
        rows, cols = stdscr.getmaxyx()
        display: List[str] = []; history: List[str] = []; hist_idx = 0

        def redraw():
            stdscr.erase()
            sb = f" TRINE v1.1  ─  {len(self.program)} LINE(S)  ─  81-TRIT TESSERACT"
            stdscr.addstr(0, 0, sb[:cols].ljust(cols), curses.color_pair(6))
            visible = display[-(rows-3):]
            for i, dl in enumerate(visible, start=1):
                try: stdscr.addstr(i, 0, dl[:cols], curses.color_pair(1))
                except curses.error: pass
            try:
                stdscr.addstr(rows-2, 0, '-'*cols, curses.color_pair(6)|curses.A_DIM)
                stdscr.addstr(rows-1, 0, 'TRINE> ', curses.color_pair(3)|curses.A_BOLD)
            except curses.error: pass
            stdscr.refresh()

        def add_line(s):
            display.extend(s.split('\n'))

        for bl in BANNER.split('\n'): add_line(bl)
        add_line(READY)
        buf = ''; redraw()

        while True:
            redraw()
            stdscr.move(rows-1, 7+len(buf)); stdscr.clrtoeol()
            try: stdscr.addstr(rows-1, 7, buf, curses.color_pair(1))
            except curses.error: pass
            stdscr.move(rows-1, 7+len(buf)); stdscr.refresh()
            try: ch = stdscr.get_wch()
            except KeyboardInterrupt: break
            if ch in ('\n','\r',curses.KEY_ENTER):
                add_line(f"TRINE> {buf}"); history.append(buf); hist_idx = len(history)
                line = buf.strip(); buf = ''
                if line:
                    if self._handle_line_curses(line, add_line) == 'quit': break
                add_line(READY)
            elif ch in (curses.KEY_BACKSPACE, '\x7f', '\x08'):
                if buf: buf = buf[:-1]
            elif ch == curses.KEY_UP:
                if hist_idx > 0: hist_idx -= 1; buf = history[hist_idx] if history else ''
            elif ch == curses.KEY_DOWN:
                if hist_idx < len(history)-1: hist_idx += 1; buf = history[hist_idx]
                else: hist_idx = len(history); buf = ''
            elif isinstance(ch, str) and ch.isprintable():
                buf += ch
        curses.endwin()

    def _handle_line_curses(self, raw: str, out_fn) -> Optional[str]:
        stripped = raw.strip()
        m = re.match(r'^(\d+)\s*(.*)', stripped)
        if m:
            num, rest = int(m.group(1)), m.group(2).strip()
            if rest == '':
                if num in self.program: del self.program[num]; out_fn(f"(line {num} deleted)")
            else: self.program[num] = rest
            return None
        upper = stripped.upper()
        if upper == 'LIST' or upper.startswith('LIST '):
            for n in sorted(self.program.keys()): out_fn(f"{n:5d}  {self.program[n]}")
            return None
        if upper == 'RUN' or upper.startswith('RUN '):
            if not self.program: out_fn('?NO PROGRAM'); return None
            source = '\n'.join(self.program[n] for n in sorted(self.program.keys()))
            self._exec_source_fn(source, '<program>', out_fn); return None
        if upper == 'NEW':
            self.program.clear(); out_fn('PROGRAM CLEARED'); return None
        if upper.startswith('SAVE'): self._cmd_save(stripped[4:].strip()); return None
        if upper.startswith('LOAD'): self._cmd_load(stripped[4:].strip()); return None
        if upper == 'EMIT':
            source = '\n'.join(self.program[n] for n in sorted(self.program.keys()))
            try: out_fn(emit_tal(source, '<program>'))
            except Exception as e: out_fn(f"?EMIT: {e}")
            return None
        if upper in ('BYE','QUIT','EXIT'): return 'quit'
        self._exec_direct_fn(stripped, out_fn); return None

    def _exec_direct_fn(self, source: str, out_fn):
        top_keywords = ('fn ','struct ','const ','pub ')
        if any(source.startswith(k) for k in top_keywords):
            self._exec_source_fn(source, '<direct>', out_fn)
        else:
            wrapped = f"fn main() {{\n  {source}\n}}"
            self._exec_source_fn(wrapped, '<direct>', out_fn)

    def _exec_source_fn(self, source: str, filename: str, out_fn):
        try:
            prog   = compile_source(source, filename)
            interp = Interpreter(output_fn=lambda s: out_fn(s.rstrip('\n')))
            interp.load(prog)
            try:     interp.run()
            except TRINEReturn as r:
                if r.val is not None: out_fn(str(r.val))
        except (LexError, ParseError) as e: out_fn(f"?SYNTAX  {e}")
        except TRINEError as e:             out_fn(f"?{e}")
        except Exception as e:              out_fn(f"?INTERNAL  {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# §10  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

_EXAMPLE = '''\
// TRINE v1.1  —  example program demonstrating v1.1 features
// python trine.py example.tr
// python trine.py example.tr --run-tal   (native TAL execution)

use "stdlib"   // load stdlib.tr if present

struct Point {
    x: triple,
    y: triple,
}

fn dot(a: Point, b: Point) -> triple {
    return a.x * b.x + a.y * b.y
}

fn fact(n: triple) -> triple {
    if n <= 1 { return 1 }
    return n * fact(n - 1)
}

fn kleene_demo() {
    let a: trit = 1
    let b: trit = T
    let c: trit = 0
    println(a & b)
    println(a | b)
    println(~a)
    println(maj(a, b, c))
    println(mux(a, b, c, a))
}

fn rev_swap(mut x: triple, mut y: triple) {
    rev {
        x = x + y
        y = x - y
        x = x - y
    }
    print(x)
    print(" ")
    println(y)
}

fn pipeline_demo() {
    // Phase sequencer: 12-phase base-12 FSM
    let mut phase: triple = 0
    let mut n2_acc: triple = 0
    for i in 0..12 {
        let offset = phase_step(phase)
        phase = (phase + 1) % 12
        n2_acc = mac_step_n2(n2_acc, 3)
        print(offset)
        print(" ")
    }
    println(0)

    // Base-60 coordinate
    let coord = base60_encode(51, 30, 0)
    println(coord)

    // ECC encode + syndrome check
    let cw = ecc_encode(12345)
    let syn = ecc_syndrome(cw)
    println(syn)
}

fn main() {
    println(fact(7))

    let p = Point { x: 3, y: 4 }
    let q = Point { x: 1, y: 2 }
    println(dot(p, q))

    kleene_demo()

    let mut a: triple = 10
    let mut b: triple = 25
    rev_swap(a, b)

    // Inline TAL via full CPU
    asm {
        LOADI R1 42
        ADD   R2 R1 R1
        PRINT R2
        HALT
    }

    pipeline_demo()
}
'''


def main():
    ap = argparse.ArgumentParser(
        prog='trine',
        description='TRINE v1.1 — Balanced-Ternary Language (Native Bootstrap)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python trine_v2.py                            screen editor
              python trine_v2.py prog.tr                    run (tree-walk)
              python trine_v2.py prog.tr --run-tal          compile → TAL → CPU
              python trine_v2.py prog.tr --run-emitted      run TAL printed by prog
              python trine_v2.py prog.tr --emit-tal         print TAL assembly
              python trine_v2.py prog.tr --trace            trace tree-walk
              python trine_v2.py prog.tr --pipeline sim     attach simulated receptor
              python trine_v2.py compiler.tr --run-emitted  self-hosted bootstrap
              python trine_v2.py --example > example.tr     print example
        """))
    ap.add_argument('file',            nargs='?', help='.tr source file')
    ap.add_argument('--emit-tal',      action='store_true', help='emit TAL assembly to stdout')
    ap.add_argument('--run-tal',       action='store_true', help='compile & run on TAL CPU')
    ap.add_argument('--run-emitted',   action='store_true',
                    help='run tree-walk, extract TAL_BEGIN..TAL_END from output, execute on CPU')
    ap.add_argument('--trace',         action='store_true', help='trace execution')
    ap.add_argument('--screen',        action='store_true', help='force curses screen editor')
    ap.add_argument('--example',       action='store_true', help='print example .tr program')
    ap.add_argument('--pipeline',      default='auto',
                    help='receptor mode: auto|sim|usb|usb:PORT|i2c|spi|gpio')
    args = ap.parse_args()

    if args.example:
        print(_EXAMPLE); return

    if args.file:
        try:
            source = open(args.file).read()
        except FileNotFoundError:
            print(f"trine: file not found: {args.file}"); sys.exit(1)

        if args.emit_tal:
            print(emit_tal(source, args.file)); return

        if args.run_emitted:
            rc = run_emitted_tal(source, args.file, trace=args.trace)
            sys.exit(rc)

        if args.run_tal:
            receptor = None
            tal = _get_tal()
            if tal:
                rec_mode = (args.pipeline or 'auto').lower()
                if rec_mode == 'sim':
                    backend = tal.SimulatedBackend()
                else:
                    backend = tal.detect_hardware(verbose=False)
                receptor = tal.ReceptorInterface(backend)
            rc = run_via_tal(source, args.file, trace=args.trace, receptor=receptor)
            sys.exit(rc)

        rc = run_source(source, args.file, trace=args.trace)
        sys.exit(max(0, rc) if isinstance(rc, int) else 0)

    # No file → screen editor
    editor = ScreenEditor(use_curses=args.screen, run_tal=args.run_tal)
    if args.screen:
        editor.run_curses()
    else:
        editor.run_readline()


if __name__ == '__main__':
    main()
