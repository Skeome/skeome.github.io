# Ternary-AL v3.1 — Architecture & ISA Reference

*Analogue-Hermetic Ternary Research Core, v3.1*
*Author: Skeome*

---

## Table of Contents

1. [Overview](#overview)
2. [What Changed: v2.0 → v3.0 → v3.1](#what-changed)
3. [Balanced Ternary Fundamentals](#balanced-ternary-fundamentals)
4. [Word Hierarchy](#word-hierarchy)
5. [CPU Architecture](#cpu-architecture)
6. [Instruction Encoding (27-27-27 Tesseract Layout)](#instruction-encoding)
7. [Opcode Zone Map](#opcode-zone-map)
8. [Instruction Reference](#instruction-reference)
   - [Data Movement](#data-movement)
   - [Indexed Addressing (v3.1)](#indexed-addressing-v31)
   - [Stack & Subroutines (v3.1)](#stack--subroutines-v31)
   - [Arithmetic](#arithmetic)
   - [Ternary (Kleene) Logic](#ternary-kleene-logic)
   - [Trit Manipulation (v3.1)](#trit-manipulation-v31)
   - [Shift & Rotate](#shift--rotate)
   - [Compare & Branch](#compare--branch)
   - [Debug & I/O](#debug--io)
   - [Hardware Receptor](#hardware-receptor)
   - [Non-Volatile Memory (v3.1)](#non-volatile-memory-v31)
9. [Assembler Syntax](#assembler-syntax)
10. [Two-Pass Assembler](#two-pass-assembler)
11. [Interactive Sandbox](#interactive-sandbox)
12. [Hardware Backends](#hardware-backends)
13. [Non-Volatile Store Implementation](#non-volatile-store-implementation)
14. [Kleene Logic Gate Reference](#kleene-logic-gate-reference)

---

## Overview

Ternary-AL v3.1 is a balanced ternary CPU ISA where both the data word and the
instruction word are one **Tesseract (81 trits)** wide. This is the first version
where data width equals instruction width.

v3.1 adds 15 new opcodes over v3.0 (which itself introduced the Tesseract register
width and 27-register file over v2.0): a stack discipline, subroutine calls, indexed
addressing, single-trit manipulation, an explicit 3-way ternary select, and a
non-volatile file-backed key-value store.

All arithmetic uses Julia `BigInt` internally; overflow is structurally impossible
regardless of operand size.

---

## What Changed

### v2.0 → v3.0

| Aspect | v2.0 | v3.0 |
|--------|------|------|
| Instruction layout | 9-9-9 Trinity (27 trits) | **27-27-27 Triple (81 trits)** |
| Register width | Trinity — 9 trits, ±9,841 | **Tesseract — 81 trits, ±2.21×10³⁸** |
| Register count | 10 (R0–R9) | **27 (R0–R26)** |
| Immediate range | ±9,841 (Trinity) | **±3,812,798,742,493 (Triple)** |
| Arithmetic | `Int` (overflow risk) | **`BigInt` (overflow impossible)** |
| TMAJ third source | Crammed into imm | **Native Segment-B `src3` field** |
| `assemble_instr` imm | Positional arg | **Keyword arg `imm=`** |
| Memory word | Trinity (9 trits) | **Tesseract (81 trits)** |
| Opcode values | — | **All 78 v2.0 values retained verbatim** |

### v3.0 → v3.1

| Addition | Details |
|----------|---------|
| Stack discipline | R26 = SP by convention; `stack_push!` / `stack_pop!` helpers |
| New CPU fields | `int_flag::Trit`, `ivec_base::Int` |
| Stack opcodes | PUSH, POP, CALL, RET |
| Interrupt opcodes | INT_EN, INT_DIS, IVEC, IRET |
| Indexed addressing | LOADX, LOADRR, STOREX, STORERR |
| Trit manipulation | TGET, TSET, TSWAP |
| Explicit ternary select | TSEL |
| Non-volatile memory | NVLOAD, NVSTORE; file-backed `Dict{Int,Vector{Trit}}` |
| NV persistence | `nv_load_file!()` called at sandbox startup |
| monitor display | Now shows `INT=` flag and `IVEC=` base address |
| sandbox reset | Also resets `int_flag = Neg`, `ivec_base = 0` |

**Total opcodes: 78 (v2.0) + 0 (v3.0) + 15 (v3.1) = 93**

---

## Balanced Ternary Fundamentals

Balanced ternary uses the digit set **{−1, 0, +1}**, written as **T**, **0**, **1**.

| Symbol | Int value | Meaning |
|--------|-----------|---------|
| `T` | −1 | Negative trit |
| `0` |  0 | Zero trit |
| `1` | +1 | Positive trit |

A value equals `∑ dᵢ × 3ⁱ` where `dᵢ ∈ {−1, 0, 1}`, `i` starting at 0 from LST.
Trit strings are printed **most-significant trit first** (MST on the left).

**Key identity:** Tritwise NOT equals arithmetic negation. `¬t = −t` for every trit,
so negating a register is a single pass with no carry logic needed.

**Saturation:** All arithmetic saturates to `±(3⁸¹ − 1) ÷ 3 ≈ ±2.21×10³⁸`.
The boundary is computed exactly with `BigInt`; no floating-point approximation.

---

## Word Hierarchy

| Name | Power | Trits | Range | Role in v3.1 |
|------|-------|-------|-------|--------------|
| Trit | 3⁰ | 1 | −1..+1 | Atomic unit; STATUS, int_flag |
| Tryte | 3¹ | 3 | −13..+13 | Register index fields in Segment B |
| Trinity | 3² | 9 | −9,841..+9,841 | SUB field; base encoding unit |
| **Triple** | **3³** | **27** | **±3,812,798,742,493** | **Segment width; immediate range** |
| **Tesseract** | **3⁴** | **81** | **±2.21×10³⁸** | **Register width; instruction width** |
| Pentact | 3⁵ | 243 | ±2.26×10¹¹⁵ | Defined as `SVector{243,Trit}`; reserved for v4.0 |

---

## CPU Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Registers: R0..R26  (27 registers, each 81 trits / Tesseract)      │
│    R0  = constant Zero (writes silently discarded)                   │
│    R1..R25 = general purpose                                         │
│    R26 = Stack Pointer (SP) by convention; writable like any reg     │
├──────────────────────────────┬──────────────────────────────────────┤
│  STATUS (1 trit)             │  PC (Julia Int, 1-based trit index)  │
│  Neg / Zero / Pos            │  advances by 81 per instruction      │
├──────────────────────────────┼──────────────────────────────────────┤
│  int_flag (1 trit)           │  ivec_base (Julia Int)               │
│  Neg=disabled (default)      │  trit address of interrupt vector    │
│  Zero=masked, Pos=enabled    │  table base (v4.0: async delivery)   │
├──────────────────────────────┴──────────────────────────────────────┤
│  Memory: flat Vector{Trit}                                           │
│  Default: 81 × 729 = 59,049 trits  (729 instructions)               │
│  LOAD/STORE operate on full 81-trit Tesseract words                  │
├─────────────────────────────────────────────────────────────────────┤
│  Non-Volatile Store: Dict{Int,Vector{Trit}} backed by nv_store.bin  │
│  Loaded at sandbox startup via nv_load_file!()                       │
├─────────────────────────────────────────────────────────────────────┤
│  Receptor Interface (optional)                                       │
│  ADS1115 / MCP3008 / GPIO / Serial / Simulated stochastic           │
└─────────────────────────────────────────────────────────────────────┘
```

**STATUS** is updated to the sign of the result by most instructions.

| STATUS | Meaning |
|--------|---------|
| `Pos` | Result > 0 |
| `Zero` | Result = 0 |
| `Neg` | Result < 0 |

**int_flag** is a three-valued interrupt control trit.

| int_flag | Meaning |
|----------|---------|
| `Pos` | Interrupts enabled |
| `Zero` | Interrupts masked (held pending) |
| `Neg` | Interrupts disabled — **default at CPU creation** |

Async peripheral interrupt delivery is deferred to v4.0. In v3.1, INT_EN, INT_DIS,
IVEC, and IRET fully assemble and execute; `ivec_base` and `int_flag` are maintained
correctly for forward compatibility.

---

## Instruction Encoding

Every instruction is **81 trits** (one Tesseract) in three **27-trit Triple** segments:

```
Trits  1 – 27  │ Segment A │ Opcode        (Triple range ±3.8 trillion)
Trits 28 – 54  │ Segment B │ Register fields + modifiers
Trits 55 – 81  │ Segment C │ Immediate     (Triple range ±3.8 trillion)
```

### Segment A — Opcode (27 trits)

```
Trits  1– 9 : Major opcode   (Trinity — all 93 opcodes, values ±9841)
Trits 10–18 : Minor opcode   (Trinity — reserved, normally 0)
Trits 19–27 : Extension      (Trinity — reserved, normally 0)
```

### Segment B — Register Fields (27 trits)

```
Trits 28–30 : DST    3 trits  BT value + 13 → register index 0..26
Trits 31–33 : SRC1   3 trits  same encoding
Trits 34–36 : SRC2   3 trits
Trits 37–39 : SRC3   3 trits  native third source (TMAJ, TSEL)
Trits 40–42 : LANE   3 trits  granularity selector (groundwork for SIMD)
Trits 43–45 : FLAGS  3 trits  predication / carry-in / reserved
Trits 46–54 : SUB    9 trits  sub-opcode, shift count, or second trit position
```

**Register index encoding:** Each 3-trit Tryte encodes a BT integer −13..+13.
Adding 13 gives the register index 0..26. The all-zero Tryte maps to R13.

### Segment C — Immediate (27 trits)

Triple range ±3,812,798,742,493. Used for integer constants, trit addresses,
channel/pin numbers, trit positions (TGET/TSET/TSWAP), and NV store keys.
`LOADI` sign-extends this 27-trit field into the full 81-trit register.

---

## Opcode Zone Map

The major opcode (trits 1–9 of Segment A) uses three zones scaled by 3⁶ = 729:

```
−9841 to −5001  │ System Control    │ stack, interrupt, branch, shift, Kleene, I/O
−5000 to  5000  │ Arithmetic & Logic│ data movement, arithmetic, logic, trit ops
 5001 to  9841  │ Hardware Receptor │ ADC / SPI / GPIO / coherence / NV store
```

### Complete Opcode Table (93 total)

| Value | Mnemonic | Zone | Version |
|------:|----------|------|---------|
| −9477 | HALT | System | v2.0 |
| −9476 | RESET | System | v2.0 |
| −8748 | PRINT | System | v2.0 |
| −8747 | DUMP | System | v2.0 |
| −8746 | PRINTS | System | v2.0 |
| −8745 | PRINTI | System | v2.0 |
| −8744 | PRINTB | System | v2.0 |
| **−8019** | **PUSH** | **System** | **v3.1** |
| **−8018** | **POP** | **System** | **v3.1** |
| **−8017** | **CALL** | **System** | **v3.1** |
| **−8016** | **RET** | **System** | **v3.1** |
| **−8015** | **INT_EN** | **System** | **v3.1** |
| **−8014** | **INT_DIS** | **System** | **v3.1** |
| **−8013** | **IVEC** | **System** | **v3.1** |
| **−8012** | **IRET** | **System** | **v3.1** |
| −7290 | CMP | System | v2.0 |
| −7289 | CMPI | System | v2.0 |
| −7288 | MIN | System | v2.0 |
| −7287 | MAX | System | v2.0 |
| −6561 | JMP | System | v2.0 |
| −6560 | JEZ | System | v2.0 |
| −6559 | JNZ | System | v2.0 |
| −6558 | JGT | System | v2.0 |
| −6557 | JLT | System | v2.0 |
| −6556 | JGEZ | System | v2.0 |
| −6555 | JLEZ | System | v2.0 |
| −5832 | LSHIFT | System | v2.0 |
| −5831 | RSHIFT | System | v2.0 |
| −5830 | LSHIFTN | System | v2.0 |
| −5829 | RSHIFTN | System | v2.0 |
| −5828 | ROTL | System | v2.0 |
| −5827 | ROTR | System | v2.0 |
| −5103 | TNOT | System | v2.0 |
| −5102 | TNAND | System | v2.0 |
| −5101 | TNOR | System | v2.0 |
| −5100 | TXNOR | System | v2.0 |
| −5099 | TIMP | System | v2.0 |
| −5098 | TMUX | System | v2.0 |
| −5097 | TMAJ | System | v2.0 |
| −5096 | TCONS | System | v2.0 |
| **−5095** | **TSEL** | **System** | **v3.1** |
| −4374 | TXOR | A&L | v2.0 |
| −4373 | TXORI | A&L | v2.0 |
| −3645 | TOR | A&L | v2.0 |
| −3644 | TORI | A&L | v2.0 |
| −2916 | TAND | A&L | v2.0 |
| −2915 | TANDI | A&L | v2.0 |
| −2187 | DIV | A&L | v2.0 |
| −2186 | DIVI | A&L | v2.0 |
| −2185 | MOD | A&L | v2.0 |
| −2184 | MODI | A&L | v2.0 |
| −1458 | MUL | A&L | v2.0 |
| −1457 | MULI | A&L | v2.0 |
| −729 | STORE | A&L | v2.0 |
| −728 | STORER | A&L | v2.0 |
| −727 | STOREI | A&L | v2.0 |
| **−726** | **STOREX** | **A&L** | **v3.1** |
| **−725** | **STORERR** | **A&L** | **v3.1** |
| 0 | NOP | A&L | v2.0 |
| 729 | LOAD | A&L | v2.0 |
| 730 | LOADI | A&L | v2.0 |
| 731 | LOADR | A&L | v2.0 |
| **732** | **LOADX** | **A&L** | **v3.1** |
| **733** | **LOADRR** | **A&L** | **v3.1** |
| 1458 | MOV | A&L | v2.0 |
| 1459 | XCHG | A&L | v2.0 |
| 2187 | ADD | A&L | v2.0 |
| 2188 | ADDI | A&L | v2.0 |
| 2916 | SUB | A&L | v2.0 |
| 2917 | SUBI | A&L | v2.0 |
| 2918 | NEG | A&L | v2.0 |
| 2919 | ABS | A&L | v2.0 |
| 3645 | INC | A&L | v2.0 |
| 3646 | DEC | A&L | v2.0 |
| 3647 | SIGN | A&L | v2.0 |
| **3648** | **TGET** | **A&L** | **v3.1** |
| **3649** | **TSET** | **A&L** | **v3.1** |
| **3650** | **TSWAP** | **A&L** | **v3.1** |
| 4374 | SSET | A&L | v2.0 |
| 5103 | RECEP | HW | v2.0 |
| 5104 | SENSE | HW | v2.0 |
| 5105 | SAMP_DB | HW | v2.0 |
| 5832 | SETTH_P | HW | v2.0 |
| 5833 | SETTH_N | HW | v2.0 |
| 5834 | RCLEAR | HW | v2.0 |
| 5835 | RSTAT | HW | v2.0 |
| 6561 | QUERY_I2C | HW | v2.0 |
| 6562 | WRITE_I2C | HW | v2.0 |
| 7290 | QUERY_SPI | HW | v2.0 |
| 7291 | WRITE_SPI | HW | v2.0 |
| 8019 | GPIO_READ | HW | v2.0 |
| 8020 | GPIO_WRITE | HW | v2.0 |
| **8748** | **NVLOAD** | **HW** | **v3.1** |
| **8749** | **NVSTORE** | **HW** | **v3.1** |
| 9477 | COHERE | HW | v2.0 |
| 9478 | ARRAY_N | HW | v2.0 |
| 9479 | GAIN | HW | v2.0 |

---

## Instruction Reference

**Notation:**
- `Rd` — destination register (R0–R26; writes to R0 are silently discarded)
- `Ra`, `Rb`, `Rc`, `Rs`, `Rsel` — source registers
- `imm` — immediate, Triple range ±3,812,798,742,493
- `pos` — trit position integer 0–80 (0 = LST, 80 = MST)
- Operands are **space-separated** (no commas); mnemonics are **case-insensitive**
- STATUS is updated to the sign of the result unless noted otherwise

---

### Data Movement

| Syntax | Operation | Notes |
|--------|-----------|-------|
| `LOAD Rd imm` | `Rd = mem[imm]` | 81-trit Tesseract word from trit-address `imm` |
| `LOADI Rd imm` | `Rd = imm` | Sign-extends 27-trit Triple into 81-trit register |
| `LOADR Rd Rs` | `Rd = mem[Rs]` | Indirect — address is the value of `Rs` |
| `STORE Rs imm` | `mem[imm] = Rs` | Writes `Rs` to trit-address `imm` |
| `STORER Rs Ra` | `mem[Ra] = Rs` | Indirect — address taken from `Ra` |
| `STOREI Rs imm` | `mem[Rs] = imm` | Address from `Rs`; immediate value written |
| `MOV Rd Rs` | `Rd = Rs` | Register copy |
| `XCHG Rd Rs` | `Rd ↔ Rs` | Swap; STATUS = new Rd |

---

### Indexed Addressing (v3.1)

Eliminates the explicit ADD instruction before every array or struct access.

| Syntax | Operation | Notes |
|--------|-----------|-------|
| `LOADX Rd Ra imm` | `Rd = mem[Ra + imm]` | Base register + immediate offset |
| `LOADRR Rd Ra Rb` | `Rd = mem[Ra + Rb]` | Both components from registers |
| `STOREX Rs Ra imm` | `mem[Ra + imm] = Rs` | `Rs` = value; `Ra` = base address |
| `STORERR Rs Ra Rb` | `mem[Ra + Rb] = Rs` | `Rs` = value; address = Ra + Rb |

Computed addresses are clamped to `[1, length(memory)]`.

---

### Stack & Subroutines (v3.1)

**R26 is the Stack Pointer (SP) by convention.** It is architecturally designated
but never hardware-enforced — SP must be initialised by the programmer before any
PUSH or CALL. The stack **grows downward**: PUSH decrements SP by 81 before writing;
POP reads, then increments SP by 81.

| Syntax | Operation | Notes |
|--------|-----------|-------|
| `PUSH Rs` | `R26 −= 81; mem[R26] = Rs` | Stack overflow prints `[STACK] Stack overflow!` |
| `POP Rd` | `Rd = mem[R26]; R26 += 81` | Stack underflow prints `[STACK] Stack underflow!` |
| `CALL imm` | `PUSH(PC + 81); PC = imm` | Saves return address; jumps to subroutine |
| `RET` | `PC = POP()` | Returns to saved address; does not modify STATUS |
| `INT_EN` | `int_flag = Pos` | Enable interrupt delivery |
| `INT_DIS` | `int_flag = Neg` | Disable interrupts |
| `IVEC imm` | `ivec_base = imm` | Set interrupt vector table base trit-address |
| `IRET` | `PC = POP(); int_flag = Pos` | Return from interrupt handler; re-enables interrupts |

CALL and RET do not disturb STATUS. INT_EN/INT_DIS/IVEC/IRET do not update STATUS.

**Subroutine example:**
```asm
LOADI R26 50000  ; initialise SP to top of stack area
CALL  DOUBLE     ; pushes PC+81, jumps to DOUBLE
PRINT R2         ; executes after RET
HALT

DOUBLE:
  LOADI R1 21
  MULI  R2 R1 2
  RET
```

---

### Arithmetic

All results are saturated to the Tesseract range (±2.21×10³⁸). Full-width `BigInt`
products are computed before clamping; no intermediate overflow is possible.

| Syntax | Operation |
|--------|-----------|
| `ADD Rd Ra Rb` | `Rd = Ra + Rb` |
| `ADDI Rd Ra imm` | `Rd = Ra + imm` |
| `SUB Rd Ra Rb` | `Rd = Ra − Rb` |
| `SUBI Rd Ra imm` | `Rd = Ra − imm` |
| `MUL Rd Ra Rb` | `Rd = Ra × Rb` (saturating) |
| `MULI Rd Ra imm` | `Rd = Ra × imm` |
| `DIV Rd Ra Rb` | `Rd = Ra ÷ Rb` (div/0: STATUS=Neg, Rd unchanged) |
| `DIVI Rd Ra imm` | `Rd = Ra ÷ imm` |
| `MOD Rd Ra Rb` | `Rd = Ra mod Rb` (sign follows dividend) |
| `MODI Rd Ra imm` | `Rd = Ra mod imm` |
| `INC Rd` | `Rd += 1` (in-place, saturating) |
| `DEC Rd` | `Rd −= 1` (in-place, saturating) |
| `NEG Rd Rs` | `Rd = −Rs` — tritwise NOT = arithmetic negation (BT identity) |
| `ABS Rd Rs` | `Rd = \|Rs\|` (saturating) |
| `SIGN Rd Rs` | `Rd = sign(Rs)` — sparse 81-trit word, all zeros except LST = ±1 |
| `MIN Rd Ra Rb` | `Rd = min(Ra, Rb)` |
| `MAX Rd Ra Rb` | `Rd = max(Ra, Rb)` |
| `SSET Rs` | `STATUS = sign(Rs)` — **no register write** |

---

### Ternary (Kleene) Logic

All operations are **tritwise across all 81 trits**. Kleene strong three-valued logic.

| Syntax | Operation |
|--------|-----------|
| `TNOT Rd Rs` | `Rd = ¬Rs` — T↔1, 0→0 |
| `TAND Rd Ra Rb` | `Rd = Ra ∧ Rb` — min per trit |
| `TANDI Rd Ra imm` | `Rd = Ra ∧ imm` |
| `TOR Rd Ra Rb` | `Rd = Ra ∨ Rb` — max per trit |
| `TORI Rd Ra imm` | `Rd = Ra ∨ imm` |
| `TXOR Rd Ra Rb` | `Rd = Ra ⊕ Rb` — `OR(AND(a,¬b),AND(¬a,b))` per trit |
| `TXORI Rd Ra imm` | `Rd = Ra ⊕ imm` |
| `TNAND Rd Ra Rb` | `Rd = ¬(Ra ∧ Rb)` |
| `TNOR Rd Ra Rb` | `Rd = ¬(Ra ∨ Rb)` |
| `TXNOR Rd Ra Rb` | `Rd = ¬(Ra ⊕ Rb)` |
| `TIMP Rd Ra Rb` | `Rd = Ra → Rb` — `OR(¬Ra,Rb)` per trit |
| `TMUX Rd Ra Rb` | Status-implicit MUX — Pos→Ra, Zero→Rb, Neg→¬Ra |
| `TMAJ Rd Ra Rb Rc` | `Rd = majority(Ra,Rb,Rc)` — Rc is native Segment-B src3 field |
| `TCONS Rd Ra Rb` | Consensus — Pos if sum>1, Neg if sum<−1, else Zero per trit |
| `TSEL Rd Rsel Ra Rb Rc` | Explicit select by sign(Rsel) — see below |

**TSEL detail:** `Rd = Ra` if `sign(Rsel) = Neg`; `Rd = Rb` if `sign(Rsel) = Zero`;
`Rd = Rc` if `sign(Rsel) = Pos`. The selector is an explicit register rather than the
implicit STATUS trit. Rc's register index is encoded in the **SUB field** of Segment B.
Assembler syntax requires five register tokens: `TSEL Rd Rsel Ra Rb Rc`.

**TMUX vs TSEL:** Use TMUX in tight loops where STATUS is already set by a prior
arithmetic or compare instruction. Use TSEL when the selector is a computed value
that must not disturb STATUS.

---

### Trit Manipulation (v3.1)

Single-trit operations for flag registers, packed struct access, and signal encoding.
Trit positions are **0-indexed** (0 = LST, 80 = MST).

| Syntax | Operation |
|--------|-----------|
| `TGET Rd Rs pos` | `Rd[LST] = Rs[pos]`; all other trits of Rd = Zero; STATUS = extracted trit |
| `TSET Rd Ra Rb pos` | `Rd = Ra` with `Ra[pos]` replaced by `Rb[LST]`; rest of Ra preserved |
| `TSWAP Rd Rs posB posA` | Swap `Rs[posA]` and `Rs[posB]` into Rd |

**TSWAP assembler argument order:** The third token (first integer) becomes the
**SUB field** (posB); the fourth token (second integer) becomes the **imm field**
(posA). Both are positions 0–80.

**Example — test a flag bit:**
```asm
LOADI R1 -1       ; R1 = all T (every trit = Neg)
TGET  R2 R1 3     ; R2[LST] = R1[3] = T; STATUS = Neg
; STATUS is now Neg, so JLT or TMUX can branch on it
```

**Example — set a flag bit:**
```asm
LOADI R3 1        ; R3[LST] = 1 (Pos)
TSET  R4 R1 R3 7  ; R4 = R1 with trit[7] set to Pos
```

---

### Shift & Rotate

Operations work across the full 81-trit register. Shifts are zero-filling.

| Syntax | Operation |
|--------|-----------|
| `LSHIFT Rd Rs` | `Rd = Rs << 1` trit (LST becomes Zero) |
| `RSHIFT Rd Rs` | `Rd = Rs >> 1` trit (MST becomes Zero) |
| `LSHIFTN Rd Rs Rn` | `Rd = Rs << \|Rn\|` trits |
| `RSHIFTN Rd Rs Rn` | `Rd = Rs >> \|Rn\|` trits |
| `ROTL Rd Rs` | Rotate left 1 trit (LST wraps to MST) |
| `ROTR Rd Rs` | Rotate right 1 trit (MST wraps to LST) |

`LSHIFTN`/`RSHIFTN` use the **absolute value** of Rn; counts are clamped to
`[0, 81]`. Left-shifting N trits multiplies by 3ᴺ (until saturation); right-shifting
N trits divides by 3ᴺ, truncating toward zero.

---

### Compare & Branch

Jump targets are **absolute trit addresses** (1-based). Instruction N starts at
`1 + (N−1) × 81`. Always use labels — raw addresses grow fast.

| Syntax | Condition | Action |
|--------|-----------|--------|
| `CMP Ra Rb` | — | `STATUS = sign(Ra − Rb)`; no register write |
| `CMPI Ra imm` | — | `STATUS = sign(Ra − imm)`; no register write |
| `JMP imm` | always | `PC = imm` |
| `JEZ imm` | STATUS == Zero | `PC = imm` |
| `JNZ imm` | STATUS != Zero | `PC = imm` |
| `JGT imm` | STATUS == Pos | `PC = imm` |
| `JLT imm` | STATUS == Neg | `PC = imm` |
| `JGEZ imm` | STATUS != Neg (≥ 0) | `PC = imm` |
| `JLEZ imm` | STATUS != Pos (≤ 0) | `PC = imm` |

---

### Debug & I/O

| Syntax | Action |
|--------|--------|
| `PRINT Rd` | Print Rd as 81-trit string and BigInt decimal |
| `PRINTI imm` | Print `imm` as decimal |
| `PRINTB Rd imm` | Print Rd in base `imm`; supported: 9, 12, 27, 60, 81 |
| `PRINTS Rd` | Print null-terminated trit string at `mem[Rd]`; each Tryte = one char |
| `DUMP` | Print all R1–R26, STATUS, int_flag, ivec_base, PC |
| `NOP` | No operation |
| `HALT` | Stop execution |
| `RESET` | Clear R1–R26, STATUS, PC=1, int_flag=Neg, ivec_base=0; memory preserved |
| `RCLEAR` | Flush receptor history; reset sample count |

---

### Hardware Receptor

| Syntax | Action |
|--------|--------|
| `RECEP Rd imm` | Single sample from receptor channel `imm` → Rd |
| `SENSE Rd imm` | Take `imm` samples; majority-vote channel 0 → Rd |
| `SAMP_DB Rd` | `Rd[LST]` = dead-band state (Zero if in dead-band) |
| `SETTH_P Rs` | Positive threshold = `Rs / 1000` volts |
| `SETTH_N Rs` | Negative threshold = `Rs / 1000` volts |
| `RSTAT Rd` | `Rd = n_channels + sample_count × 27` |
| `QUERY_I2C Rd imm` | ADS1115 channel `imm` voltage × 1000 → Rd |
| `WRITE_I2C Rs imm` | Write Rs to ADS1115 register `imm` |
| `QUERY_SPI Rd imm` | MCP3008 channel `imm` voltage × 1000 → Rd |
| `WRITE_SPI Rs imm` | Write Rs to MCP3008 config register `imm` |
| `GPIO_READ Rd imm` | GPIO pin `imm` trit state → Rd |
| `GPIO_WRITE Rs imm` | Write LST of Rs to GPIO pin `imm` |
| `COHERE imm` | Set simulated ξ = `imm / 1000` (0..1000) |
| `ARRAY_N imm` | Set simulated array size N = `imm` |
| `GAIN Rd` | `Rd = ξ²N²` (operator gain, clamped to ±9841) |

**Threshold encoding:** `LOADI R1 750; SETTH_P R1` sets the positive threshold to 0.750 V.

**RSTAT encoding:** n_channels occupies the Tryte-scale low field; sample_count
(mod 9841) is multiplied by 27 before addition, using natural ternary place value.

**Binary boundaries:** WRITE_I2C, WRITE_SPI, GPIO_WRITE, and nv_store.bin serialisation
use binary encoding only where the hardware or file-system interface requires it.

---

### Non-Volatile Memory (v3.1)

| Syntax | Action |
|--------|--------|
| `NVLOAD Rd imm` | `Rd = nv_store[imm]` — returns Zero-filled Tesseract if key absent |
| `NVSTORE Rs imm` | `nv_store[imm] = Rs` — persisted to `nv_store.bin` immediately |

Keys are integers (Triple range). Values are full 81-trit Tesseract words. The store
is loaded from `nv_store.bin` automatically at sandbox startup. If the file does not
exist, the store starts empty and is created on the first NVSTORE.

**Example — persist a calibration value:**
```asm
LOADI R1 750        ; 0.750 V threshold in millivolts
NVSTORE R1 1        ; persist to key 1
; ... next session ...
NVLOAD  R2 1        ; restore: R2 = 750
SETTH_P R2          ; apply threshold
```

---

## Assembler Syntax

### Basic Rules

```
MNEMONIC ARG1 ARG2 ...   ; optional comment
LABEL:                   ; defines label at current trit address
```

- Operands are **space-separated** (no commas)
- Mnemonics and register names are **case-insensitive**
- Everything after `;` is a comment; blank lines are ignored
- Labels are stored **uppercase** internally

### Operand Types

| Type | Format | Range | Examples |
|------|--------|-------|---------|
| Register | `Rn` | R0–R26 | `R0` `R13` `R26` |
| Immediate | Decimal integer | Triple ±3.8 trillion | `42` `-100` `50000` |
| Label | Name string | Resolves to trit address | `LOOP` `MYFUNC` |

### assemble_instr Signature (Julia)

```julia
assemble_instr(opcode, dst=0, src1=0, src2=0, src3=0;
               lane=0, flags=0, sub=0, imm=0)
```

`imm` is a keyword argument. Register arguments are R-indices 0–26.

### Full Syntax Table

**Data movement:**
```
LOAD   Rd imm        LOADI  Rd imm        LOADR   Rd Rs
LOADX  Rd Ra imm     LOADRR Rd Ra Rb
STORE  Rs imm        STORER Rs Ra         STOREI  Rs imm
STOREX Rs Ra imm     STORERR Rs Ra Rb
MOV    Rd Rs         XCHG   Rd Rs
```

**Stack & subroutines:**
```
PUSH   Rs            POP    Rd
CALL   imm           RET
INT_EN               INT_DIS
IVEC   imm           IRET
```

**Arithmetic:**
```
ADD    Rd Ra Rb      ADDI   Rd Ra imm
SUB    Rd Ra Rb      SUBI   Rd Ra imm
MUL    Rd Ra Rb      MULI   Rd Ra imm
DIV    Rd Ra Rb      DIVI   Rd Ra imm
MOD    Rd Ra Rb      MODI   Rd Ra imm
INC    Rd            DEC    Rd
NEG    Rd Rs         ABS    Rd Rs
SIGN   Rd Rs         SSET   Rs
MIN    Rd Ra Rb      MAX    Rd Ra Rb
```

**Ternary logic:**
```
TNOT   Rd Rs
TAND   Rd Ra Rb      TANDI  Rd Ra imm
TOR    Rd Ra Rb      TORI   Rd Ra imm
TXOR   Rd Ra Rb      TXORI  Rd Ra imm
TNAND  Rd Ra Rb      TNOR   Rd Ra Rb
TXNOR  Rd Ra Rb      TIMP   Rd Ra Rb
TMUX   Rd Ra Rb      TMAJ   Rd Ra Rb Rc
TCONS  Rd Ra Rb
TSEL   Rd Rsel Ra Rb Rc       ; Rc index → SUB field
```

**Trit manipulation:**
```
TGET   Rd Rs pos
TSET   Rd Ra Rb pos
TSWAP  Rd Rs posB posA        ; posB → SUB field, posA → imm field
```

**Shift & rotate:**
```
LSHIFT  Rd Rs        RSHIFT  Rd Rs
LSHIFTN Rd Rs Rn     RSHIFTN Rd Rs Rn
ROTL    Rd Rs        ROTR    Rd Rs
```

**Compare & branch:**
```
CMP    Ra Rb         CMPI   Ra imm
JMP    imm           JEZ    imm    JNZ  imm
JGT    imm           JLT    imm
JGEZ   imm           JLEZ   imm
```

**Debug / I/O:**
```
PRINT  Rd            PRINTI imm           PRINTB Rd imm
PRINTS Rd            DUMP
NOP                  HALT                 RESET    RCLEAR
```

**Hardware receptor:**
```
RECEP    Rd imm      SENSE    Rd imm      SAMP_DB  Rd
SETTH_P  Rs          SETTH_N  Rs          RSTAT    Rd
QUERY_I2C Rd imm     WRITE_I2C Rs imm
QUERY_SPI Rd imm     WRITE_SPI Rs imm
GPIO_READ  Rd imm    GPIO_WRITE Rs imm
COHERE   imm         ARRAY_N  imm         GAIN     Rd
```

**Non-volatile memory:**
```
NVLOAD   Rd imm      NVSTORE  Rs imm
```

---

## Two-Pass Assembler

`assemble_program(lines::Vector{<:AbstractString})` returns an `AssemblyProgram`:

- `.code` — `Vector{Trit}`, exactly 81 trits per instruction
- `.labels` — `Dict{String,Int}`, label → 1-based trit address

**Pass 1:** Strips comments, uppercases, records label definitions (lines ending `:`)
at their current trit address. Labels stored as `String` (not `SubString`) to avoid
type dispatch issues with `Dict{String,Int}`.

**Pass 2:** Assembles every non-label line; resolves all label references.

**Trit address arithmetic:** Instruction N (0-indexed) starts at `1 + N × 81`.
Instruction 10 starts at trit 811 (not 271 as in v2.0 where `INSTR_LEN` was 27).

All parser functions (`parse_assembly_line`, `_parse_reg`, `_parse_arg`,
`assemble_program`) accept `AbstractString`, so `strip()` and `split()` output
feeds directly without explicit type conversion.

---

## Interactive Sandbox

Start with `julia Balanced_Ternary_V3_1.jl`, choose 1–7 at the menu.
The NV store is loaded from `nv_store.bin` on startup automatically.

At the `T-AL>` prompt: type any assembly instruction to assemble-and-execute at
the current PC, or type one of the sandbox commands below.

### Sandbox Commands

| Command | Action |
|---------|--------|
| `run` | Run until HALT or max_cycles (100,000) |
| `step` | Execute one instruction |
| `reset` | Clear R1–R26, STATUS, PC=1, int_flag=Neg, ivec_base=0; memory preserved |
| `monitor` | Full CPU state: all registers, STATUS, INT, IVEC, PC, next instruction |
| `status` | Show STATUS and PC only |
| `trace [on\|off]` | Toggle per-instruction trace (mnemonic + PC after each step) |
| `memdump ADDR LEN` | Dump LEN Tesseract words (81 trits each) from trit-address ADDR |
| `convert N` | Show decimal N in balanced-ternary and all base encodings |
| `receptor` | Show receptor backend type, channels, thresholds, sample count, majority vote |
| `help` | Print the inline reference card |
| `quit` / `exit` | Shut down sandbox |

### Monitor Display

```
── CPU STATE ───────────────────────────────────────────────────────────
PC=82  STATUS=1  INT=DIS  IVEC=0
Next: CALL (dst=0 src1=0 src2=0 src3=0 imm=406)
Reg  │ Value (81-trit string)  │ Decimal                        │ diff
─────┼─────────────────────────┼────────────────────────────────┼──────
 R1  │ 000...001               │                              1 │ (changed)
 R26 │ 000...000               │                              0 │       ← SP
```

`INT=` shows `EN` (Pos), `MASK` (Zero), or `DIS` (Neg).
`IVEC=` shows the interrupt vector base trit-address.
`(changed)` marks registers that differ from the last step/run.

---

## Hardware Backends

| Backend | Hardware | Channels | Auto-detect path |
|---------|----------|----------|-----------------|
| `ADS1115Backend` | I²C ADC, 16-bit | 4 | `/dev/i2c-1`, addr 0x48 |
| `MCP3008Backend` | SPI ADC, 10-bit | 8 | `/dev/spidev0.0` |
| `SerialBackend` | UART | 4 | User-specified port |
| `GPIOBackend` | RPi GPIO digital | N | User-specified pin pairs |
| `SimulatedBackend` | Julia stochastic | 8 | Always available as fallback |

**Auto-detection order:** ADS1115 → MCP3008 → Serial → GPIO → SimulatedBackend.

**Simulated stochastic resonance model:**
```
operator_gain = ξ² × N²
voltage = signal_prob × N(0,1) + directed_signal × ξ × gain × 0.1
```
Tune with `COHERE imm` (ξ = imm/1000) and `ARRAY_N imm` (N = imm).

---

## Non-Volatile Store Implementation

```
File: nv_store.bin  (in working directory, created on first NVSTORE)
Format: repeated entries, no header
  Key   : 8 bytes  (Julia Int64, little-endian native)
  Value : 81 bytes (one byte per trit: T→0x00, Zero→0x01, Pos→0x02)
```

The in-memory store is `const _nv_store = Dict{Int, Vector{Trit}}()`. On every
`NVSTORE`, the entire dict is rewritten atomically to disk. `NVLOAD` on an absent
key returns a Zero-filled 81-trit register without error.

The byte encoding `T→0, 0→1, 1→2` keeps all stored bytes non-negative. This is
the only place in the entire system where a binary encoding scheme is used; it is
a necessary file-system I/O boundary.

---

## Kleene Logic Gate Reference

T = −1, 0 = 0, 1 = +1.
XOR: `OR(AND(a,NOT(b)), AND(NOT(a),b))`.
IMP: `OR(NOT(a),b)`.
CONS: Pos if a+b > 1, Neg if a+b < −1, else Zero.

| a | b | AND | OR  | XOR | NAND | NOR | XNOR | IMP | CONS |
|---|---|-----|-----|-----|------|-----|------|-----|------|
| T | T |  T  |  T  |  T  |   1  |  1  |  T   |  1  |  T   |
| T | 0 |  T  |  0  |  0  |   1  |  0  |  0   |  1  |  0   |
| T | 1 |  T  |  1  |  1  |   1  |  T  |  T   |  1  |  0   |
| 0 | T |  T  |  0  |  0  |   1  |  0  |  0   |  0  |  0   |
| 0 | 0 |  0  |  0  |  0  |   0  |  0  |  0   |  0  |  0   |
| 0 | 1 |  0  |  1  |  0  |   0  |  T  |  0   |  1  |  0   |
| 1 | T |  T  |  1  |  1  |   1  |  T  |  T   |  T  |  0   |
| 1 | 0 |  0  |  1  |  0  |   0  |  T  |  0   |  0  |  0   |
| 1 | 1 |  1  |  1  |  T  |   T  |  T  |  1   |  1  |  1   |

**Unary NOT:** T→1, 0→0, 1→T

**XOR:** Gives 0 when either input is 0. For two non-zero inputs: 1 if they differ
in sign (T,1 or 1,T); T if they match (T,T or 1,1). This is Kleene-derived XOR,
not modular addition.

**IMP:** `IMP(a,b) = 0` only when `a=Pos` and `b` is not Pos. `IMP(0,b) = 0` for
all `b` (indeterminate antecedent yields indeterminate implication).

**CONS:** Non-Zero only when both inputs are non-Zero and share the same sign.

---

*End of Ternary-AL v3.1 Reference*
