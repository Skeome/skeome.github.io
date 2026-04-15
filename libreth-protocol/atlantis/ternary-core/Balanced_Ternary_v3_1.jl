#===============================================================================#
# ANALOGUE-HERMETIC TERNARY RESEARCH CORE, v3.1
# Author: Skeome
#
# Ternary-AL v3.1: Tesseract-Opcodes on a Tesseract-Word Architecture
#
# ISA v3.0 Changes from v2.0:
#   - 27-27-27 Tesseract instruction layout (was 9-9-9 Trinity)
#       Segment A (trits  1 to 27) : Opcode     : full Triple space ±3,812,798,742,493
#       Segment B (trits 28 to 54) : Register fields + modifiers
#         B[ 1- 3] DST   : 3 trits → R0..R26 (BT offset: trit value + 13)
#         B[ 4- 6] SRC1  : 3 trits
#         B[ 7- 9] SRC2  : 3 trits
#         B[10-12] SRC3  : 3 trits  (native third source; TMAJ no longer uses imm)
#         B[13-15] LANE  : granularity selector (groundwork for SIMD)
#         B[16-18] FLAGS : predication / carry-in / reserved
#         B[19-27] SUB   : Trinity sub-opcode, shift count, or second trit index
#       Segment C (trits 55 to 81) : Immediate  : full Triple space ±3,812,798,742,493
#   - Major opcode occupies trits 1-9 of Segment A; all 78 v2.0 opcode constants
#     are numerically unchanged — re-assembling v2.0 source requires no edits
#   - Registers: R0..R26, 27 total (was R0..R9); R0 still constant Zero
#   - Register width: 81 trits / Tesseract (was 9 trits / Trinity)
#   - All arithmetic promoted to BigInt; Int64 overflow is structurally impossible
#   - LOADI  : sign-extends 27-trit Triple immediate into full 81-trit register
#   - SIGN   : full 81-trit Tesseract sparse output (was Trinity)
#   - TMAJ   : SRC3 is native Segment-B field (was crammed into imm field)
#   - assemble_instr: imm is now a keyword argument (imm=) to distinguish from
#     the new src3/lane/flags/sub positional fields
#   - Memory word = Tesseract (81 trits); LOAD/STORE address in 81-trit units
#
# ISA v3.1 Additions (from architecture review):
#
#   ── Stack & Subroutines (group −11, base −8019) ─────────────────────────────
#   - R26 is the architectural Stack Pointer (SP) by convention; writable as any
#     general-purpose register, never hardware-enforced (pure BT discipline)
#   - Stack grows downward; PUSH decrements SP by REG_WIDTH (81) before writing
#   - PUSH Rs      : SP −= 81; mem[SP] = Rs
#   - POP  Rd      : Rd = mem[SP]; SP += 81
#   - CALL imm     : PUSH(PC + INSTR_LEN); PC = imm
#   - RET          : POP into PC
#   - INT_EN       : int_flag = Pos  (enable interrupt delivery)
#   - INT_DIS      : int_flag = Neg  (disable; interrupts held pending)
#   - IVEC  imm    : set interrupt vector base address = imm
#   - IRET         : POP into PC; int_flag = Pos  (return from interrupt)
#     Interrupt flag is a Trit: Neg=disabled, Zero=masked, Pos=enabled
#     Full async interrupt delivery (peripheral-triggered) is deferred to v4.0;
#     IVEC/INT_EN/INT_DIS/IRET are fully defined and assembled in v3.1
#
#   ── Indexed Addressing (LOAD group +1, STORE group −1) ──────────────────────
#   - LOADX  Rd Ra imm  : Rd = mem[Ra + imm]    (base + immediate offset)
#   - LOADRR Rd Ra Rb   : Rd = mem[Ra + Rb]     (base + register offset)
#   - STOREX Rs Ra imm  : mem[Ra + imm] = Rs
#   - STORERR Rs Ra Rb  : mem[Ra + Rb]  = Rs
#     Enables O(1) array indexing and struct field access without an explicit ADD
#
#   ── Trit Manipulation (group +5 extension, base 3648) ───────────────────────
#   - TGET  Rd Rs imm      : extract trit at position imm (0–80) from Rs
#                            store as LST (least-significant trit) of Rd
#   - TSET  Rd Ra Rb imm   : copy LST(Rb) into Ra at trit position imm → Rd
#                            src1=Ra (source word), src2=Rb (value carrier)
#   - TSWAP Rd Rs imm      : swap trits at positions imm and SUB within Rs → Rd
#                            second position encoded in Segment B SUB field;
#                            first use of SUB carrying runtime operand data
#     These three instructions cover all single-trit field operations needed for
#     balanced ternary signal encoding, packed struct access, and flag registers
#
#   ── Explicit Ternary Select (group −7 extension, opcode −5095) ──────────────
#   - TSEL Rd Rsel Ra Rb Rc : Rd = Ra if sign(Rsel)=Neg,
#                                    Rb if sign(Rsel)=Zero,
#                                    Rc if sign(Rsel)=Pos
#                             Rc register index encoded in SUB field
#     Complements TMUX (status-implicit) with an explicit register-controlled
#     3-way branch without touching status or requiring a prior CMP
#
#   ── Non-Volatile Memory (group +12, base 8748) ──────────────────────────────
#   - NVLOAD  Rd imm  : load Tesseract word from NV store key imm → Rd
#   - NVSTORE Rs imm  : persist Rs to NV store key imm
#     Backed by a file-keyed store (default: "nv_store.bin" in working directory)
#     The mechanism is pluggable; the ISA boundary is kept clean and
#     hardware-independent. Designed for long-term collapse-pattern archives and
#     receptor calibration state
#
#   ── Design decisions and deferrals ──────────────────────────────────────────
#   - No PUSH/POP implicit on CALL/RET to keep SP visible and auditable;
#     the programmer controls the stack frame entirely
#   - TSEL uses the SUB field for Rc rather than a fifth positional argument,
#     keeping the assembler parser uniform (max four register tokens per line)
#   - Higher-order Kleene (TMAJ with N>3 inputs) deferred to v4.0 SIMD lane work
#   - Interrupt priority levels and vector table format are v4.0 concerns;
#     v3.1 provides the instruction boundary only
#   - Binary is used only where the hardware boundary requires it:
#     I²C/SPI wire protocol, sysfs GPIO, NV file I/O block size
#
# Opcode summary — new in v3.1:
#   System (group −11):  PUSH POP CALL RET INT_EN INT_DIS IVEC IRET
#   A&L (LOAD/STORE ext): LOADX LOADRR STOREX STORERR
#   A&L (group +5 ext):  TGET TSET TSWAP
#   A&L (group −7 ext):  TSEL
#   HW (group +12):      NVLOAD NVSTORE
#   Total opcodes: 78 (v2.0) + 0 (v3.0) + 15 (v3.1) = 93
#
# Word hierarchy (powers of 3):
#   Trit      3^0    1 trit    Range: −1  to +1
#   Tryte     3^1    3 trits   Range: −13 to +13
#   Trinity   3^2    9 trits   Range: −9,841 to +9,841
#   Triple    3^3   27 trits   Range: ±3,812,798,742,493
#   Tesseract 3^4   81 trits   Range: ±2.21×10^38       ← register & instruction word
#   Pentact   3^5  243 trits   Range: ±2.26×10^115      ← defined, reserved for v4.0
#===============================================================================#

using StaticArrays
using Printf
using Dates
using Random

#-------------------------------------------------------------------------------
# Trit Enumeration
#-------------------------------------------------------------------------------

@enum Trit Neg=-1 Zero=0 Pos=1

const TRIT_SYMBOL = Dict(Neg => 'T', Zero => '0', Pos => '1')

trits_to_string(tr::Vector{Trit})              = join(TRIT_SYMBOL[t] for t in reverse(tr))
trits_to_string(t::SVector{L, Trit}) where {L} = trits_to_string(collect(t))

#-------------------------------------------------------------------------------
# Kleene Strong Three-Valued Logic Gates
#-------------------------------------------------------------------------------

tNOT(t::Trit)            = Trit(-Int(t))
tAND(a::Trit, b::Trit)   = Trit(min(Int(a), Int(b)))
tOR(a::Trit, b::Trit)    = Trit(max(Int(a), Int(b)))
tNAND(a::Trit, b::Trit)  = tNOT(tAND(a, b))
tNOR(a::Trit, b::Trit)   = tNOT(tOR(a, b))
tXOR(a::Trit, b::Trit)   = tOR(tAND(a, tNOT(b)), tAND(tNOT(a), b))
tXNOR(a::Trit, b::Trit)  = tNOT(tXOR(a, b))
tIMP(a::Trit, b::Trit)   = tOR(tNOT(a), b)
tCONS(a::Trit, b::Trit)  = Int(a)+Int(b) > 1 ? Pos : Int(a)+Int(b) < -1 ? Neg : Zero

# 3-input MUX: selector s picks from (a=Neg, b=Zero, c=Pos)
function tMUX(s::Trit, a::Trit, b::Trit, c::Trit)
    s == Neg  && return a
    s == Zero && return b
    return c
end

# Majority vote on three trits
function tMAJ(a::Trit, b::Trit, c::Trit)
    s = Int(a) + Int(b) + Int(c)
    s > 0 ? Pos : s < 0 ? Neg : Zero
end

# Element-wise majority on three equal-length vectors
function tMAJ3(a::Vector{Trit}, b::Vector{Trit}, c::Vector{Trit})
    n = min(length(a), length(b), length(c))
    [tMAJ(a[i], b[i], c[i]) for i in 1:n]
end

function tritwise_gate(a::Vector{Trit}, b::Vector{Trit}, gate::Function, len::Int=9)
    pa = vcat(a[1:min(end,len)], fill(Zero, max(0, len-length(a))))
    pb = vcat(b[1:min(end,len)], fill(Zero, max(0, len-length(b))))
    [gate(x, y) for (x, y) in zip(pa, pb)]
end

function tritwise_not(a::Vector{Trit})
    [tNOT(t) for t in a]
end

tSHIFT_UP(t::Trit)   = t == Pos ? Neg : Trit(Int(t) + 1)
tSHIFT_DOWN(t::Trit) = t == Neg ? Pos : Trit(Int(t) - 1)

import Base: +, &, |
(Base.:+)(a::Trit, b::Trit) = tSUM(a, b)
(Base.:&)(a::Trit, b::Trit) = tAND(a, b)
(Base.:|)(a::Trit, b::Trit) = tOR(a, b)

#-------------------------------------------------------------------------------
# Arithmetic
#-------------------------------------------------------------------------------

function tSUM(a::Trit, b::Trit)
    s = Int(a) + Int(b)
    s ==  2 && return Neg   # overflow: +1+1 = T (carry Pos)
    s == -2 && return Pos   # underflow: T+T = 1 (carry Neg)
    Trit(s)
end

function tFULL_ADDER(a::Trit, b::Trit, c_in::Trit)
    total = Int(a) + Int(b) + Int(c_in)
    s_out = if total in (3, 0, -3); Zero
            elseif total in (1, -2); Pos
            else; Neg; end
    c_out = total > 1 ? Pos : total < -1 ? Neg : Zero
    s_out, c_out
end

function add_trytes(a::Vector{Trit}, b::Vector{Trit})
    len    = max(length(a), length(b))
    va     = vcat(a, fill(Zero, len - length(a)))
    vb     = vcat(b, fill(Zero, len - length(b)))
    result = Trit[]
    carry  = Zero
    for i in 1:len
        s, carry = tFULL_ADDER(va[i], vb[i], carry)
        push!(result, s)
    end
    carry != Zero && push!(result, carry)
    result
end

sub_trytes(a::Vector{Trit}, b::Vector{Trit})   = add_trytes(a, tritwise_not(b))
increment_tryte(w::Vector{Trit})                = add_trytes(w, [Pos])
decrement_tryte(w::Vector{Trit})                = sub_trytes(w, [Pos])

function multiply_trytes(a::Vector{Trit}, b::Vector{Trit})
    result = [Zero]
    for (i, t) in enumerate(b)
        partial = t == Pos ? copy(a) :
                  t == Neg ? tritwise_not(a) : [Zero]
        result = add_trytes(result, vcat(fill(Zero, i-1), partial))
    end
    result
end

function divide_trytes(a::Vector{Trit}, b::Vector{Trit})
    nb = balanced_ternary_to_int(b)
    nb == 0 && return (fill(Zero, REG_WIDTH), true)
    na = balanced_ternary_to_int(a)
    (int_to_balanced(div(na, nb), REG_WIDTH), false)
end

function mod_trytes(a::Vector{Trit}, b::Vector{Trit})
    nb = balanced_ternary_to_int(b)
    nb == 0 && return (fill(Zero, REG_WIDTH), true)
    na = balanced_ternary_to_int(a)
    (int_to_balanced(rem(na, nb), REG_WIDTH), false)   # sign follows dividend (BT convention)
end

function shift_left_tryte(w::Vector{Trit}, n::Int=1)
    n = clamp(n, 0, length(w))
    n == 0 && return copy(w)
    vcat(fill(Zero, n), w)[1:length(w)]
end

function shift_right_tryte(w::Vector{Trit}, n::Int=1)
    n = clamp(n, 0, length(w))
    n == 0 && return copy(w)
    vcat(w, fill(Zero, n))[n+1:n+length(w)]
end

function rotate_left_tryte(w::Vector{Trit}, n::Int=1)
    len = length(w); n = mod(n, max(len, 1))
    n == 0 && return copy(w)
    vcat(w[n+1:end], w[1:n])
end

function rotate_right_tryte(w::Vector{Trit}, n::Int=1)
    len = length(w); n = mod(n, max(len, 1))
    n == 0 && return copy(w)
    vcat(w[end-n+1:end], w[1:end-n])
end

function abs_trytes(a::Vector{Trit}, len::Int=REG_WIDTH)
    n       = balanced_ternary_to_int(a)
    max_val = (BigInt(3)^len - 1) ÷ 3
    int_to_balanced(min(abs(n), max_val), len)
end

#-------------------------------------------------------------------------------
# Analogue Boundary -- decode_analogue is the single entry point for all
# receptor paths.  Dead-band ±threshold maps to Zero (longitudinal mode).
#-------------------------------------------------------------------------------

function decode_analogue(voltage::Float64;
                         pos_threshold::Float64=0.5,
                         neg_threshold::Float64=-0.5)
    voltage > pos_threshold  && return Pos
    voltage < neg_threshold  && return Neg
    Zero
end

#-------------------------------------------------------------------------------
# Memory & Data Formatting
#-------------------------------------------------------------------------------

mutable struct TritRegister; value::Trit; end

mutable struct TritMemory
    state::Trit
    last_voltage::Float64
    last_update::DateTime
end
TritMemory(state::Trit) = TritMemory(state, 0.0, now())

function clock_pulse!(mem::TritMemory, v::Float64;
                      pos_threshold::Float64=0.5,
                      neg_threshold::Float64=-0.5)
    mem.state        = decode_analogue(v; pos_threshold, neg_threshold)
    mem.last_voltage = v
    mem.last_update  = now()
    mem.state
end

function balanced_ternary_to_int(trits::Vector{Trit})
    isempty(trits) && return BigInt(0)
    sum(BigInt(Int(t)) * BigInt(3)^(i-1) for (i, t) in enumerate(trits))
end

function int_to_balanced(n::Integer, len::Int)
    digits = Int[]
    temp   = n
    while temp != 0 || length(digits) < len
        r = temp % 3
        if r == 2 || r == -1;  r = -1; temp = div(temp + 1, 3)
        elseif r == 1 || r == -2; r = 1; temp = div(temp - 1, 3)
        else; temp = div(temp, 3); end
        push!(digits, r)
        length(digits) >= len && temp == 0 && break
    end
    while length(digits) < len; push!(digits, 0); end
    [Trit(d) for d in digits[1:len]]
end

tPRINT(trits::Vector{Trit}) = println(join(TRIT_SYMBOL[t] for t in reverse(trits)))
tPRINT(t::Trit)             = println(TRIT_SYMBOL[t])

#-------------------------------------------------------------------------------
# Power-of-3 Hierarchy (StaticArrays)
#-------------------------------------------------------------------------------

const Tryte     = SVector{3,   Trit}
const Trinity   = SVector{9,   Trit}
const Triple    = SVector{27,  Trit}
const Tesseract = SVector{81,  Trit}
const Pentact   = SVector{243, Trit}   # 3^5 — next rung of the hierarchy

function balanced_to_int(trits::SVector{L, Trit}) where {L}
    sum(BigInt(Int(trits[i])) * BigInt(3)^(i-1) for i in 1:L)
end

tryte_from_int(n::Integer)     = Tryte(int_to_balanced(n, 3))
trinity_from_int(n::Integer)   = Trinity(int_to_balanced(n, 9))
triple_from_int(n::Integer)    = Triple(int_to_balanced(n, 27))
tesseract_from_int(n::Integer) = Tesseract(int_to_balanced(n, 81))
pentact_from_int(n::Integer)   = Pentact(int_to_balanced(n, 243))

int_from_tryte(t::Tryte)         = balanced_to_int(t)
int_from_trinity(t::Trinity)     = balanced_to_int(t)
int_from_triple(t::Triple)       = balanced_to_int(t)
int_from_tesseract(t::Tesseract) = balanced_to_int(t)
int_from_pentact(t::Pentact)     = balanced_to_int(t)

function tPRINT(trits::SVector{L, Trit}) where {L}
    println(join(TRIT_SYMBOL[trits[i]] for i in L:-1:1))
end

function saturating_add(a::SVector{L, Trit}, b::SVector{L, Trit}) where {L}
    max_val = (BigInt(3)^L - 1) ÷ 3
    int_res = clamp(balanced_ternary_to_int(add_trytes(collect(a), collect(b))),
                    -max_val, max_val)
    SVector{L, Trit}(int_to_balanced(int_res, L))
end

function saturating_add_vec(a::Vector{Trit}, b::Vector{Trit}, len::Int=REG_WIDTH)
    max_val = (BigInt(3)^len - 1) ÷ 3
    int_res = clamp(balanced_ternary_to_int(add_trytes(a, b)), -max_val, max_val)
    int_to_balanced(int_res, len)
end

#-------------------------------------------------------------------------------
# Multi-base Encoding
#-------------------------------------------------------------------------------

function encode_base9(trits::Vector{Trit})
    n = length(trits) ÷ 2
    reverse([Int(trits[2i-1]) + 3*Int(trits[2i]) + 4 for i in 1:n])
end

function encode_base12(trits::Vector{Trit})
    n = length(trits) ÷ 3
    reverse([mod(Int(trits[3i-2]) + 3*Int(trits[3i-1]) + 9*Int(trits[3i]) + 6, 12) for i in 1:n])
end

function encode_base27(trits::Vector{Trit})
    n = length(trits) ÷ 3
    reverse([Int(trits[3i-2]) + 3*Int(trits[3i-1]) + 9*Int(trits[3i]) + 13 for i in 1:n])
end

function encode_base60(trits::Vector{Trit})
    n = length(trits) ÷ 4
    reverse([mod(Int(trits[4i-3]) + 3*Int(trits[4i-2]) + 9*Int(trits[4i-1]) + 27*Int(trits[4i]) + 30, 60) for i in 1:n])
end

function encode_base81(trits::Vector{Trit})
    n = length(trits) ÷ 4
    reverse([Int(trits[4i-3]) + 3*Int(trits[4i-2]) + 9*Int(trits[4i-1]) + 27*Int(trits[4i]) + 40 for i in 1:n])
end

# Generic SVector dispatch for all encoders, one method covers every word size
for fn in (:encode_base9, :encode_base12, :encode_base27, :encode_base60, :encode_base81)
    @eval $fn(t::SVector{L, Trit}) where {L} = $fn(collect(t))
end

function print_base9(trits::Vector{Trit})
    @printf("Base-9  : %s  →  %s\n",
            trits_to_string(trits),
            join(string(d) for d in encode_base9(trits)))
end

function print_base12(trits::Vector{Trit})
    @printf("Base-12 : %s  →  (%s)\n",
            trits_to_string(trits),
            join((string(d) for d in encode_base12(trits)), ", "))
end

function print_base27(trits::Vector{Trit})
    @printf("Base-27 : %s  →  (%s)\n",
            trits_to_string(trits),
            join((string(d) for d in encode_base27(trits)), ", "))
end

function print_base60(trits::Vector{Trit})
    @printf("Base-60 : %s  →  [%s]\n",
            trits_to_string(trits),
            join((@sprintf("%02d", d) for d in encode_base60(trits)), ":"))
end

function print_base81(trits::Vector{Trit})
    @printf("Base-81 : %s  →  (%s)\n",
            trits_to_string(trits),
            join((string(d) for d in encode_base81(trits)), ", "))
end

function print_all_bases(trits::Vector{Trit})
    print_base9(trits); print_base12(trits)
    print_base27(trits); print_base60(trits); print_base81(trits)
end

# Generic SVector dispatch for all printers, same pattern as encoders
for fn in (:print_base9, :print_base12, :print_base27,
           :print_base60, :print_base81, :print_all_bases)
    @eval $fn(t::SVector{L, Trit}) where {L} = $fn(collect(t))
end

#===============================================================================#
# HARDWARE RECEPTOR ABSTRACTION LAYER
#===============================================================================#

abstract type ReceptorBackend end

#-------------------------------------------------------------------------------
# 1. ADS1115, 16-bit I²C ADC
#-------------------------------------------------------------------------------

const ADS1115_CONV_REG   = 0x00
const ADS1115_CONFIG_REG = 0x01
const ADS1115_PGA_4096   = 0b001
const ADS1115_MUX = [0b100, 0b101, 0b110, 0b111]
const ADS1115_LSB_MV_4096 = 0.125e-3

mutable struct ADS1115Backend <: ReceptorBackend
    fd::Int
    bus::Int
    address::UInt8
    n_channels::Int
    pos_threshold::Float64
    neg_threshold::Float64
end

function ADS1115Backend(; bus::Int=1, address::UInt8=0x48,
                          n_channels::Int=4,
                          pos_threshold::Float64=0.5,
                          neg_threshold::Float64=-0.5)
    dev = "/dev/i2c-$bus"
    isfile(dev) || error("I²C device $dev not found")
    fd = ccall(:open, Cint, (Cstring, Cint), dev, 2)
    fd < 0 && error("Cannot open $dev")
    @printf("[ADS1115] Initialised on %s addr=0x%02X %d channels\n",
            dev, address, n_channels)
    ADS1115Backend(fd, bus, address, n_channels, pos_threshold, neg_threshold)
end

function ads1115_read_channel(b::ADS1115Backend, ch::Int)
    mux = ADS1115_MUX[clamp(ch+1, 1, 4)]
    cfg_hi = UInt8(0x80 | (mux << 4) | (ADS1115_PGA_4096 << 1) | 0x01)
    cfg_lo = UInt8(0x83)
    buf_w  = UInt8[ADS1115_CONFIG_REG, cfg_hi, cfg_lo]
    ccall(:write, Cssize_t, (Cint, Ptr{UInt8}, Csize_t), b.fd, buf_w, 3)
    sleep(0.01)
    reg_w = UInt8[ADS1115_CONV_REG]
    ccall(:write, Cssize_t, (Cint, Ptr{UInt8}, Csize_t), b.fd, reg_w, 1)
    buf_r = zeros(UInt8, 2)
    ccall(:read, Cssize_t, (Cint, Ptr{UInt8}, Csize_t), b.fd, buf_r, 2)
    raw = Int16((Int16(buf_r[1]) << 8) | buf_r[2])
    Float64(raw) * ADS1115_LSB_MV_4096
end

read_voltages(b::ADS1115Backend)  = [ads1115_read_channel(b, ch) for ch in 0:b.n_channels-1]
close_backend(b::ADS1115Backend)  = ccall(:close, Cint, (Cint,), b.fd)

#-------------------------------------------------------------------------------
# 2. MCP3008, 10-bit SPI ADC
#-------------------------------------------------------------------------------

mutable struct MCP3008Backend <: ReceptorBackend
    fd::Int; vref::Float64; n_channels::Int
    pos_threshold::Float64; neg_threshold::Float64
end

function MCP3008Backend(; bus::Int=0, device::Int=0, vref::Float64=3.3,
                          n_channels::Int=8,
                          pos_threshold::Float64=0.5,
                          neg_threshold::Float64=-0.5)
    dev = "/dev/spidev$bus.$device"
    isfile(dev) || error("SPI device $dev not found")
    fd = ccall(:open, Cint, (Cstring, Cint), dev, 2)
    fd < 0 && error("Cannot open $dev")
    mode  = UInt8(0);     ccall(:ioctl, Cint, (Cint, Culong, Ptr{UInt8}),   fd, 0x40016B01, Ref(mode))
    speed = UInt32(1_350_000); ccall(:ioctl, Cint, (Cint, Culong, Ptr{UInt32}), fd, 0x40046B04, Ref(speed))
    @printf("[MCP3008] Initialised on %s VREF=%.2fV %d channels\n", dev, vref, n_channels)
    MCP3008Backend(fd, vref, n_channels, pos_threshold, neg_threshold)
end

function mcp3008_read_channel(b::MCP3008Backend, ch::Int)
    tx = UInt8[0x01, UInt8(0x80 | (ch << 4)), 0x00]
    rx = zeros(UInt8, 3)
    ccall(:write, Cssize_t, (Cint, Ptr{UInt8}, Csize_t), b.fd, tx, 3)
    ccall(:read,  Cssize_t, (Cint, Ptr{UInt8}, Csize_t), b.fd, rx, 3)
    raw = ((Int(rx[2]) & 0x03) << 8) | Int(rx[3])
    (Float64(raw) / 1023.0) * b.vref - b.vref / 2.0
end

read_voltages(b::MCP3008Backend)  = [mcp3008_read_channel(b, ch) for ch in 0:b.n_channels-1]
close_backend(b::MCP3008Backend)  = ccall(:close, Cint, (Cint,), b.fd)

#-------------------------------------------------------------------------------
# 3. Serial / UART backend
#-------------------------------------------------------------------------------

mutable struct SerialBackend <: ReceptorBackend
    port::String; baud::Int; n_channels::Int
    pos_threshold::Float64; neg_threshold::Float64
    _io::IO; _last_voltages::Vector{Float64}
end

function SerialBackend(; port::String="/dev/ttyUSB0", baud::Int=115200,
                         n_channels::Int=4,
                         pos_threshold::Float64=0.5,
                         neg_threshold::Float64=-0.5)
    isfile(port) || error("Serial port $port not found")
    run(`stty -F $port $baud raw -echo`)
    io = open(port, "r+")
    @printf("[Serial] Initialised on %s @ %d baud %d channels\n",
            port, baud, n_channels)
    SerialBackend(port, baud, n_channels, pos_threshold, neg_threshold,
                  io, zeros(Float64, n_channels))
end

function read_voltages(b::SerialBackend)
    try
        line   = readline(b._io)
        parts  = split(replace(line, r"V\d+:" => ""), ',')
        vs     = [v for p in parts if (v = tryparse(Float64, strip(p))) !== nothing]
        length(vs) >= b.n_channels && (b._last_voltages = vs[1:b.n_channels])
    catch; end
    copy(b._last_voltages)
end
close_backend(b::SerialBackend) = close(b._io)

#-------------------------------------------------------------------------------
# 4. GPIO Digital Threshold Backend (RPi5)
#-------------------------------------------------------------------------------

const GPIOCHIP_RPi5 = "/dev/gpiochip4"
const GPIOCHIP_RPi4 = "/dev/gpiochip0"

mutable struct GPIOChannel
    pin_pos::Int; pin_neg::Int; fd_pos::Int; fd_neg::Int
end

mutable struct GPIOBackend <: ReceptorBackend
    chip::String; channels::Vector{GPIOChannel}
    pos_threshold::Float64; neg_threshold::Float64; n_channels::Int
end

function GPIOBackend(pin_pairs::Vector{Tuple{Int,Int}};
                     pos_threshold::Float64=0.5, neg_threshold::Float64=-0.5)
    chip = isfile(GPIOCHIP_RPi5) ? GPIOCHIP_RPi5 : GPIOCHIP_RPi4
    isfile(chip) || error("No GPIO chip found")
    chip_fd = ccall(:open, Cint, (Cstring, Cint), chip, 0)
    chip_fd < 0 && error("Cannot open $chip")
    channels = GPIOChannel[]
    for (pp, pn) in pin_pairs
        _gpio_export(pp); _gpio_export(pn)
        _gpio_direction(pp, "in"); _gpio_direction(pn, "in")
        fd_p = ccall(:open, Cint, (Cstring, Cint), "/sys/class/gpio/gpio$(pp)/value", 0)
        fd_n = ccall(:open, Cint, (Cstring, Cint), "/sys/class/gpio/gpio$(pn)/value", 0)
        push!(channels, GPIOChannel(pp, pn, fd_p, fd_n))
    end
    ccall(:close, Cint, (Cint,), chip_fd)
    @printf("[GPIO] Initialised on %s %d channels\n", chip, length(pin_pairs))
    GPIOBackend(chip, channels, pos_threshold, neg_threshold, length(pin_pairs))
end

function _gpio_export(pin::Int)
    p = "/sys/class/gpio/gpio$pin"
    isdir(p) || try write("/sys/class/gpio/export", string(pin)); sleep(0.05) catch end
end
function _gpio_direction(pin::Int, dir::String)
    try write("/sys/class/gpio/gpio$pin/direction", dir) catch end
end
function _gpio_read(fd::Int)::Bool
    buf = Vector{UInt8}(undef, 2)
    ccall(:lseek, Int64, (Cint, Int64, Cint), fd, 0, 0)
    n = ccall(:read, Cssize_t, (Cint, Ptr{UInt8}, Csize_t), fd, buf, 2)
    n > 0 && buf[1] == UInt8('1')
end

function read_voltages(b::GPIOBackend)
    result = Float64[]
    for ch in b.channels
        hi = _gpio_read(ch.fd_pos); lo = _gpio_read(ch.fd_neg)
        push!(result, hi && !lo ? 1.0 : lo && !hi ? -1.0 : 0.0)
    end
    result
end

function close_backend(b::GPIOBackend)
    for ch in b.channels
        ccall(:close, Cint, (Cint,), ch.fd_pos)
        ccall(:close, Cint, (Cint,), ch.fd_neg)
        try write("/sys/class/gpio/unexport", string(ch.pin_pos)) catch end
        try write("/sys/class/gpio/unexport", string(ch.pin_neg)) catch end
    end
end

#-------------------------------------------------------------------------------
# 5. Simulated Backend, stochastic resonance, pure Julia
#-------------------------------------------------------------------------------

mutable struct SimulatedBackend <: ReceptorBackend
    n_channels::Int; signal_probability::Float64
    operator_coherence::Float64; operator_n::Int
    directed_signal::Float64
    pos_threshold::Float64; neg_threshold::Float64
end

SimulatedBackend(; n_channels::Int=8, signal_probability::Float64=0.1,
                   operator_coherence::Float64=0.0, operator_n::Int=1,
                   directed_signal::Float64=0.6,
                   pos_threshold::Float64=0.5, neg_threshold::Float64=-0.5) =
    SimulatedBackend(n_channels, signal_probability, operator_coherence,
                     operator_n, directed_signal, pos_threshold, neg_threshold)

operator_gain(b::SimulatedBackend) = b.operator_coherence^2 * Float64(b.operator_n)^2

function read_voltages(b::SimulatedBackend)
    G = operator_gain(b)
    [clamp(b.signal_probability * randn() +
           b.directed_signal * b.operator_coherence * G * 0.1, -1.5, 1.5)
     for _ in 1:b.n_channels]
end
close_backend(::SimulatedBackend) = nothing

#-------------------------------------------------------------------------------
# Receptor Interface, wraps any backend with TritMemory cell array
#-------------------------------------------------------------------------------

mutable struct ReceptorInterface
    backend::ReceptorBackend
    cells::Vector{TritMemory}
    history::Vector{Vector{Trit}}
    history_depth::Int
    sample_count::Int
    pos_threshold::Float64
    neg_threshold::Float64
end

function ReceptorInterface(backend::ReceptorBackend; history_depth::Int=100)
    n     = backend.n_channels
    cells = [TritMemory(Zero) for _ in 1:n]
    ReceptorInterface(backend, cells, Vector{Vector{Trit}}(), history_depth,
                      0, backend.pos_threshold, backend.neg_threshold)
end

function sample!(ri::ReceptorInterface)
    voltages = read_voltages(ri.backend)
    states   = Trit[]
    for (i, v) in enumerate(voltages)
        s = clock_pulse!(ri.cells[i], v;
                         pos_threshold=ri.pos_threshold,
                         neg_threshold=ri.neg_threshold)
        push!(states, s)
    end
    push!(ri.history, states)
    length(ri.history) > ri.history_depth && popfirst!(ri.history)
    ri.sample_count += 1
    states
end

function majority_vote(ri::ReceptorInterface, n_samples::Int=10)
    n_samples = min(n_samples, length(ri.history))
    n_samples == 0 && return fill(Zero, ri.backend.n_channels)
    result = Trit[]
    for ch in 1:ri.backend.n_channels
        counts = Dict(Neg => 0, Zero => 0, Pos => 0)
        for s in ri.history[end-n_samples+1:end]
            ch <= length(s) && (counts[s[ch]] += 1)
        end
        push!(result, argmax(counts))
    end
    result
end

function show_receptor_status(ri::ReceptorInterface)
    println("\n── RECEPTOR LAYER ─────────────────────────────────────────")
    @printf("Backend  : %s\n", typeof(ri.backend))
    @printf("Channels : %d   Samples: %d\n", ri.backend.n_channels, ri.sample_count)
    if isa(ri.backend, SimulatedBackend)
        b = ri.backend
        @printf("Coherence: ξ=%.3f  N=%d  Gain=%.2e\n",
                b.operator_coherence, b.operator_n, operator_gain(b))
    end
    println("CH  │ State │  Voltage   │ Updated")
    println("────┼───────┼────────────┼────────────────────")
    for (i, cell) in enumerate(ri.cells)
        @printf(" %2d │   %s   │ %+9.4f V │ %s\n",
                i-1, TRIT_SYMBOL[cell.state], cell.last_voltage,
                Dates.format(cell.last_update, "HH:MM:SS.sss"))
    end
    if length(ri.history) >= 3
        mv = majority_vote(ri, min(10, length(ri.history)))
        @printf("Majority vote (last %d): %s\n",
                min(10, length(ri.history)), join(TRIT_SYMBOL[t] for t in mv))
    end
    println("────────────────────────────────────────────────────────────")
end

#-------------------------------------------------------------------------------
# Hardware auto-detection
#-------------------------------------------------------------------------------

function detect_hardware(; n_channels::Int=4,
                           i2c_bus::Int=1, ads1115_addr::UInt8=0x48,
                           spi_bus::Int=0, spi_dev::Int=0,
                           serial_port::String="",
                           gpio_pairs::Vector{Tuple{Int,Int}}=Tuple{Int,Int}[],
                           pos_threshold::Float64=0.5,
                           neg_threshold::Float64=-0.5,
                           verbose::Bool=true)::ReceptorBackend
    verbose && println("[Hardware] Beginning receptor backend detection...")

    if isfile("/dev/i2c-$i2c_bus")
        try
            b = ADS1115Backend(; bus=i2c_bus, address=ads1115_addr,
                                 n_channels=min(n_channels, 4),
                                 pos_threshold, neg_threshold)
            verbose && println("[Hardware] ADS1115 found")
            return b
        catch e; verbose && @printf("[Hardware] ADS1115 unavailable: %s\n", e); end
    end

    if isfile("/dev/spidev$spi_bus.$spi_dev")
        try
            b = MCP3008Backend(; bus=spi_bus, device=spi_dev,
                                 n_channels=min(n_channels, 8),
                                 pos_threshold, neg_threshold)
            verbose && println("[Hardware] MCP3008 found")
            return b
        catch e; verbose && @printf("[Hardware] MCP3008 unavailable: %s\n", e); end
    end

    if !isempty(serial_port) && isfile(serial_port)
        try
            b = SerialBackend(; port=serial_port, n_channels, pos_threshold, neg_threshold)
            verbose && println("[Hardware] Serial found on $serial_port")
            return b
        catch e; verbose && @printf("[Hardware] Serial unavailable: %s\n", e); end
    end

    if !isempty(gpio_pairs) && isfile(GPIOCHIP_RPi5)
        try
            b = GPIOBackend(gpio_pairs; pos_threshold, neg_threshold)
            verbose && println("[Hardware] GPIO found")
            return b
        catch e; verbose && @printf("[Hardware] GPIO unavailable: %s\n", e); end
    end

    verbose && println("[Hardware] SimulatedBackend active (stochastic resonance)")
    SimulatedBackend(; n_channels, pos_threshold, neg_threshold)
end

function trigger_receptors!(cpu_mem::Vector{Trit}, region_start::Int, region_len::Int,
                             prob::Float64=0.15;
                             receptor::Union{ReceptorInterface,Nothing}=nothing)
    if receptor !== nothing
        states = sample!(receptor)
        affected = 0
        for (i, state) in enumerate(states)
            addr = region_start + i - 1
            addr > length(cpu_mem) && break
            if cpu_mem[addr] == Zero && state != Zero
                cpu_mem[addr] = state; affected += 1
            end
        end
        affected > 0 && @printf("Hardware receptor: %d trit(s) committed to region %d:%d\n",
                                 affected, region_start, region_start+region_len-1)
    else
        affected = 0
        for i in region_start:min(region_start+region_len-1, length(cpu_mem))
            if cpu_mem[i] == Zero && rand() < prob
                cpu_mem[i] = rand([Neg, Pos]); affected += 1
            end
        end
        affected > 0 && @printf("Simulated receptor: %d trit(s) became active in region %d:%d\n",
                                 affected, region_start, region_start+region_len-1)
    end
end

#===============================================================================#
# CPU MODEL, Ternary-AL v2.0
#===============================================================================#

#-------------------------------------------------------------------------------
# Opcode constants, group x 3^6 (x729) scaling
# Three zones:
#   System Control    : −9841 to −5001
#   Arithmetic & Logic: −5000 to  5000
#   Hardware Receptor :  5001 to  9841
#-------------------------------------------------------------------------------

# ── System Control ─────────────────────────────────────────────────────────────
const OP_HALT    = -9477  # group −13: halt execution
const OP_RESET   = -9476  # reset PC + registers (preserve memory)
const OP_PRINT   = -8748  # group −12: print R_dst (trit / decimal / base-27)
const OP_DUMP    = -8747  # dump all registers + status + PC
const OP_PRINTS  = -8746  # print null-terminated trit string from mem[R_dst]
const OP_PRINTI  = -8745  # print Segment C immediate as decimal
const OP_PRINTB  = -8744  # print R_dst in base imm (9/12/27/60/81)
const OP_CMP     = -7290  # group −10: compare src1 − src2, update status only
const OP_CMPI    = -7289  # compare R_src1 vs immediate
const OP_MIN     = -7288  # R_dst = min(R_src1, R_src2)
const OP_MAX     = -7287  # R_dst = max(R_src1, R_src2)
const OP_JMP     = -6561  # group  −9: unconditional jump to imm
const OP_JEZ     = -6560  # jump if status == Zero
const OP_JNZ     = -6559  # jump if status != Zero
const OP_JGT     = -6558  # jump if status == Pos
const OP_JLT     = -6557  # jump if status == Neg
const OP_JGEZ    = -6556  # jump if status != Neg  (≥ 0)
const OP_JLEZ    = -6555  # jump if status != Pos  (≤ 0)
const OP_LSHIFT  = -5832  # group  −8: shift R_src1 left 1 trit → R_dst
const OP_RSHIFT  = -5831  # shift R_src1 right 1 trit → R_dst
const OP_LSHIFTN = -5830  # shift left  by amount in R_src2
const OP_RSHIFTN = -5829  # shift right by amount in R_src2
const OP_ROTL    = -5828  # rotate left  1 trit (LST wraps to MST)
const OP_ROTR    = -5827  # rotate right 1 trit (MST wraps to LST)
const OP_TNOT    = -5103  # group  −7: tritwise NOT (¬ = arithmetic negation)
const OP_TNAND   = -5102  # tritwise NAND
const OP_TNOR    = -5101  # tritwise NOR
const OP_TXNOR   = -5100  # tritwise XNOR
const OP_TIMP    = -5099  # ternary implication: OR(NOT(a), b)
const OP_TMUX    = -5098  # status-implicit MUX: Pos→src1, Zero→src2, Neg→¬src1
const OP_TMAJ    = -5097  # majority vote (3 regs; third index in imm field)
const OP_TCONS   = -5096  # consensus: Pos if sum>1, Neg if sum<−1, else Zero

# ── Arithmetic & Logic ─────────────────────────────────────────────────────────
const OP_TXOR    = -4374  # group  −6: tritwise XOR
const OP_TXORI   = -4373  # TXOR with immediate
const OP_TOR     = -3645  # group  −5: tritwise OR  (Kleene max)
const OP_TORI    = -3644  # TOR with immediate
const OP_TAND    = -2916  # group  −4: tritwise AND (Kleene min)
const OP_TANDI   = -2915  # TAND with immediate
const OP_DIV     = -2187  # group  −3: saturating division; sets Neg on div/0
const OP_DIVI    = -2186  # divide by immediate
const OP_MOD     = -2185  # balanced ternary remainder; sign follows dividend
const OP_MODI    = -2184  # modulo by immediate
const OP_MUL     = -1458  # group  −2: saturating multiply
const OP_MULI    = -1457  # multiply by immediate
const OP_STORE   = -729   # group  −1: mem[imm] = R_src1
const OP_STORER  = -728   # indirect: mem[R_src2] = R_src1
const OP_STOREI  = -727   # mem[R_src1] = Segment C immediate
const OP_NOP     =  0     # no operation
const OP_LOAD    =  729   # group  +1: R_dst = mem[imm]
const OP_LOADI   =  730   # R_dst = Segment C (no memory access)
const OP_LOADR   =  731   # indirect: R_dst = mem[R_src1]
const OP_MOV     =  1458  # group  +2: R_dst = R_src1
const OP_XCHG    =  1459  # swap R_dst ↔ R_src1
const OP_ADD     =  2187  # group  +3: saturating add
const OP_ADDI    =  2188  # add immediate: R_dst = R_src1 + imm
const OP_SUB     =  2916  # group  +4: saturating subtract
const OP_SUBI    =  2917  # subtract immediate
const OP_NEG     =  2918  # R_dst = ¬R_src1 == −R_src1 (BT identity)
const OP_ABS     =  2919  # R_dst = |R_src1| (saturating)
const OP_INC     =  3645  # group  +5: R_dst += 1 (saturating)
const OP_DEC     =  3646  # R_dst −= 1 (saturating)
const OP_SIGN    =  3647  # R_dst = sparse Trinity word for sign of R_src1
const OP_SSET    =  4374  # group  +6: set cpu.status = sign(R_src1); no write

# ── Hardware Receptor ──────────────────────────────────────────────────────────
const OP_RECEP     =  5103  # group  +7: sample receptor channel imm → R_dst
const OP_SENSE     =  5104  # majority-vote last imm samples → R_dst
const OP_SAMP_DB   =  5105  # sample dead-band state into LST of R_dst
const OP_SETTH_P   =  5832  # group  +8: set positive threshold from R_src1
const OP_SETTH_N   =  5833  # set negative threshold from R_src1
const OP_RCLEAR    =  5834  # flush receptor history buffer
const OP_RSTAT     =  5835  # encode receptor metadata into R_dst
const OP_QUERY_I2C =  6561  # group  +9: read ADS1115 register imm → R_dst
const OP_WRITE_I2C =  6562  # write R_src1 to ADS1115 register imm
const OP_QUERY_SPI =  7290  # group +10: MCP3008 channel imm → R_dst
const OP_WRITE_SPI =  7291  # write R_src1 to MCP3008 config register imm
const OP_GPIO_READ =  8019  # group +11: read GPIO pin imm trit state → R_dst
const OP_GPIO_WRITE=  8020  # write LST of R_src1 to GPIO pin imm
const OP_COHERE    =  9477  # group +13: set operator coherence ξ from imm (÷1000)
const OP_ARRAY_N   =  9478  # set operator array size N from imm
const OP_GAIN      =  9479  # compute ξ²N² → R_dst

# ── v3.1: Stack & Subroutines (group −11, base −8019) ─────────────────────────
const OP_PUSH    = -8019  # SP−=81; mem[SP]=R_src1
const OP_POP     = -8018  # R_dst=mem[SP]; SP+=81
const OP_CALL    = -8017  # PUSH(PC+INSTR_LEN); PC=imm
const OP_RET     = -8016  # POP into PC
const OP_INT_EN  = -8015  # cpu.int_flag = Pos  (enable interrupts)
const OP_INT_DIS = -8014  # cpu.int_flag = Neg  (disable interrupts)
const OP_IVEC    = -8013  # cpu.ivec_base = imm (set interrupt vector base)
const OP_IRET    = -8012  # POP into PC; cpu.int_flag = Pos

# ── v3.1: Indexed Addressing (LOAD/STORE group extensions) ────────────────────
const OP_LOADX   =  732   # R_dst = mem[R_src1 + imm]
const OP_LOADRR  =  733   # R_dst = mem[R_src1 + R_src2]
const OP_STOREX  = -726   # mem[R_src1 + imm] = R_src2
const OP_STORERR = -725   # mem[R_src1 + R_src2] = R_dst  (dst used as value here)

# ── v3.1: Trit Manipulation (group +5 extension, base 3648) ───────────────────
const OP_TGET   =  3648  # R_dst[LST] = trit at position imm (0–80) of R_src1
const OP_TSET   =  3649  # R_dst = R_src1 with trit[imm] replaced by LST(R_src2)
const OP_TSWAP  =  3650  # R_dst = R_src1 with trits[imm] and [sub] swapped

# ── v3.1: Explicit Ternary Select (group −7 extension) ────────────────────────
const OP_TSEL   = -5095  # R_dst = R_src1/R_src2/R_src3 chosen by sign(R_dst_prev)
                         # Rsel=src1, Ra=src2, Rb=src3, Rc index in SUB field

# ── v3.1: Non-Volatile Memory (group +12, base 8748) ──────────────────────────
const OP_NVLOAD  =  8748  # R_dst = nv_store[imm]
const OP_NVSTORE =  8749  # nv_store[imm] = R_src1

const INSTR_LEN   = 81    # one Tesseract  = three Triples  (27-27-27 layout)
const REG_WIDTH   = 81    # Tesseract-sized registers
const N_REGS      = 27    # R0..R26  (R0 = constant Zero, writes discarded)
const MAX_REG_VAL = (BigInt(3)^REG_WIDTH - 1) ÷ 3   # ≈ 2.21×10³⁸

# Saturate a BigInt to the register range, return as REG_WIDTH-trit vector
_sat(n::Integer) = int_to_balanced(clamp(BigInt(n), -MAX_REG_VAL, MAX_REG_VAL), REG_WIDTH)
_int(v::Vector{Trit}) = balanced_ternary_to_int(v)   # BigInt from register vector

const OPCODE_NAMES = Dict(
    OP_HALT => "HALT",  OP_RESET => "RESET",
    OP_PRINT => "PRINT", OP_DUMP => "DUMP", OP_PRINTS => "PRINTS",
    OP_PRINTI => "PRINTI", OP_PRINTB => "PRINTB",
    OP_CMP => "CMP", OP_CMPI => "CMPI", OP_MIN => "MIN", OP_MAX => "MAX",
    OP_JMP => "JMP", OP_JEZ => "JEZ", OP_JNZ => "JNZ",
    OP_JGT => "JGT", OP_JLT => "JLT", OP_JGEZ => "JGEZ", OP_JLEZ => "JLEZ",
    OP_LSHIFT => "LSHIFT", OP_RSHIFT => "RSHIFT",
    OP_LSHIFTN => "LSHIFTN", OP_RSHIFTN => "RSHIFTN",
    OP_ROTL => "ROTL", OP_ROTR => "ROTR",
    OP_TNOT => "TNOT", OP_TNAND => "TNAND", OP_TNOR => "TNOR",
    OP_TXNOR => "TXNOR", OP_TIMP => "TIMP", OP_TMUX => "TMUX",
    OP_TMAJ => "TMAJ", OP_TCONS => "TCONS",
    OP_TXOR => "TXOR", OP_TXORI => "TXORI",
    OP_TOR  => "TOR",  OP_TORI  => "TORI",
    OP_TAND => "TAND", OP_TANDI => "TANDI",
    OP_DIV => "DIV", OP_DIVI => "DIVI", OP_MOD => "MOD", OP_MODI => "MODI",
    OP_MUL => "MUL", OP_MULI => "MULI",
    OP_STORE => "STORE", OP_STORER => "STORER", OP_STOREI => "STOREI",
    OP_NOP  => "NOP",
    OP_LOAD => "LOAD", OP_LOADI => "LOADI", OP_LOADR => "LOADR",
    OP_MOV  => "MOV",  OP_XCHG  => "XCHG",
    OP_ADD  => "ADD",  OP_ADDI  => "ADDI",
    OP_SUB  => "SUB",  OP_SUBI  => "SUBI",
    OP_NEG  => "NEG",  OP_ABS   => "ABS",
    OP_INC  => "INC",  OP_DEC   => "DEC",
    OP_SIGN => "SIGN", OP_SSET  => "SSET",
    OP_RECEP => "RECEP", OP_SENSE => "SENSE", OP_SAMP_DB => "SAMP_DB",
    OP_SETTH_P => "SETTH_P", OP_SETTH_N => "SETTH_N",
    OP_RCLEAR => "RCLEAR", OP_RSTAT => "RSTAT",
    OP_QUERY_I2C => "QUERY_I2C", OP_WRITE_I2C => "WRITE_I2C",
    OP_QUERY_SPI => "QUERY_SPI", OP_WRITE_SPI => "WRITE_SPI",
    OP_GPIO_READ => "GPIO_READ", OP_GPIO_WRITE => "GPIO_WRITE",
    OP_COHERE => "COHERE", OP_ARRAY_N => "ARRAY_N", OP_GAIN => "GAIN",
    # v3.1
    OP_PUSH => "PUSH", OP_POP => "POP", OP_CALL => "CALL", OP_RET => "RET",
    OP_INT_EN => "INT_EN", OP_INT_DIS => "INT_DIS",
    OP_IVEC => "IVEC", OP_IRET => "IRET",
    OP_LOADX => "LOADX", OP_LOADRR => "LOADRR",
    OP_STOREX => "STOREX", OP_STORERR => "STORERR",
    OP_TGET => "TGET", OP_TSET => "TSET", OP_TSWAP => "TSWAP",
    OP_TSEL => "TSEL",
    OP_NVLOAD => "NVLOAD", OP_NVSTORE => "NVSTORE",
)

#-------------------------------------------------------------------------------
# CPU Struct
#-------------------------------------------------------------------------------

mutable struct CPU
    pc::Int
    memory::Vector{Trit}
    regs::Vector{Vector{Trit}}   # R1..R26 (REG_WIDTH trits each); R0 = constant Zero
    status::Trit
    running::Bool
    int_flag::Trit   # Neg=disabled, Zero=masked, Pos=enabled
    ivec_base::Int   # trit address of interrupt vector table base
end

# Default memory: 3^6 = 729 Tesseract-sized instructions
CPU(mem_size::Int = INSTR_LEN * 729) =
    CPU(1, fill(Zero, mem_size),
        [fill(Zero, REG_WIDTH) for _ in 1:(N_REGS-1)],
        Zero, true, Neg, 0)

# R26 is the architectural Stack Pointer by convention
const SP_REG = N_REGS - 1   # index 26

#-------------------------------------------------------------------------------
# Memory access helpers  (word = Tesseract, 81 trits)
#-------------------------------------------------------------------------------

function read_word(mem::Vector{Trit}, addr::Int)
    slice = addr >= 1 && addr <= length(mem) ?
            mem[addr:min(addr + REG_WIDTH - 1, length(mem))] : Trit[]
    vcat(slice, fill(Zero, max(0, REG_WIDTH - length(slice))))
end

function write_word!(mem::Vector{Trit}, addr::Int, val::Vector{Trit})
    for i in 1:REG_WIDTH
        (addr + i - 1 <= length(mem)) &&
            (mem[addr+i-1] = i <= length(val) ? val[i] : Zero)
    end
end

# R0 = constant Zero (writes silently discarded); R1..R26 are general-purpose
function get_reg(cpu::CPU, idx::Int)
    idx == 0 && return fill(Zero, REG_WIDTH)
    cpu.regs[clamp(idx, 1, N_REGS-1)]
end

function set_reg!(cpu::CPU, idx::Int, val::Vector{Trit})
    (idx < 1 || idx > N_REGS-1) && return
    n = length(val)
    cpu.regs[idx] = n >= REG_WIDTH ? val[1:REG_WIDTH] :
                                     vcat(val, fill(Zero, REG_WIDTH - n))
end

function set_status!(cpu::CPU, val::Vector{Trit})
    iv = _int(val)
    cpu.status = iv > 0 ? Pos : iv < 0 ? Neg : Zero
end

#-------------------------------------------------------------------------------
# Instruction decode  (27-27-27 Tesseract segmentation)
#
#   Segment A  trits  1- 27 : Opcode      (Triple range ±3.8 trillion)
#   Segment B  trits 28- 54 : Register fields + modifiers
#     B[1- 3] = DST   (3 trits, BT int -13..+13, add 13 → R0..R26)
#     B[4- 6] = SRC1
#     B[7- 9] = SRC2
#     B[10-12]= SRC3  (native third source; no longer crammed into imm)
#     B[13-15]= LANE  (0=scalar, 1=Triple×3, 2=Trinity×9, 3=Tryte×27)
#     B[16-18]= FLAGS (predication / carry-in / reserved)
#     B[19-27]= SUB   (Trinity-range sub-opcode or shift count)
#   Segment C  trits 55- 81 : Immediate   (Triple range ±3.8 trillion)
#-------------------------------------------------------------------------------

function decode_instruction(cpu::CPU)
    pc  = cpu.pc
    mem = cpu.memory
    len = length(mem)
    instr = vcat(pc <= len ? mem[pc:min(pc+INSTR_LEN-1, len)] : Trit[],
                 fill(Zero, max(0, INSTR_LEN - (len - pc + 1))))

    # Segment A
    opcode = _int(instr[1:27])

    # Segment B — register indices decoded with +13 offset (BT -13..+13 → 0..26)
    _ridx(t) = Int(_int(t)) + 13
    dst   = _ridx(instr[28:30])
    src1  = _ridx(instr[31:33])
    src2  = _ridx(instr[34:36])
    src3  = _ridx(instr[37:39])
    lane  = Int(_int(instr[40:42]))   # granularity selector
    flags = instr[43:45]              # raw trits — caller interprets
    sub   = Int(_int(instr[46:54]))   # Trinity sub-opcode / shift count

    # Segment C
    imm = instr[55:81]

    opcode, dst, src1, src2, src3, lane, flags, sub, imm
end

#-------------------------------------------------------------------------------
# Instruction assemble  (27-27-27 Tesseract segmentation)
# Register arguments are R-indices 0..26; imm is a keyword to avoid positional
# confusion now that src3/lane/flags/sub sit between the registers and the imm.
#-------------------------------------------------------------------------------

function assemble_instr(opcode::Integer,
                        dst::Int=0, src1::Int=0, src2::Int=0, src3::Int=0;
                        lane::Int=0, flags::Int=0, sub::Int=0,
                        imm::Integer=0)
    vcat(
        int_to_balanced(opcode,      27),   # Segment A
        int_to_balanced(dst  - 13,    3),   # Segment B: DST  (R0→-13, R26→+13)
        int_to_balanced(src1 - 13,    3),
        int_to_balanced(src2 - 13,    3),
        int_to_balanced(src3 - 13,    3),
        int_to_balanced(lane,         3),   # LANE
        int_to_balanced(flags,        3),   # FLAGS
        int_to_balanced(sub,          9),   # SUB
        int_to_balanced(imm,         27),   # Segment C
    )
end

function load_program!(cpu::CPU, program::Vector{Trit}, start::Int=1)
    for i in eachindex(program)
        addr = start + i - 1
        addr <= length(cpu.memory) && (cpu.memory[addr] = program[i])
    end
end

#-------------------------------------------------------------------------------
# Non-Volatile Store  (file-backed Dict; key = Int imm, value = Trit vector)
#-------------------------------------------------------------------------------

const NV_FILE = "nv_store.bin"
const _nv_store = Dict{Int, Vector{Trit}}()

function nv_load!(key::Int)::Vector{Trit}
    haskey(_nv_store, key) && return copy(_nv_store[key])
    fill(Zero, REG_WIDTH)
end

function nv_store!(key::Int, val::Vector{Trit})
    _nv_store[key] = copy(val)
    try
        open(NV_FILE, "w") do io
            for (k, v) in _nv_store
                write(io, Int64(k))
                write(io, UInt8[Int8(Int(t)) + 1 for t in v])  # T→0, 0→1, 1→2
            end
        end
    catch e
        @printf("[NV] Warning: could not persist store: %s\n", e)
    end
end

function nv_load_file!()
    isfile(NV_FILE) || return
    try
        open(NV_FILE, "r") do io
            entry_bytes = 8 + REG_WIDTH   # Int64 key + REG_WIDTH bytes
            while !eof(io)
                k   = read(io, Int64)
                raw = read(io, REG_WIDTH)
                length(raw) == REG_WIDTH || break
                _nv_store[Int(k)] = [Trit(Int(b) - 1) for b in raw]
            end
        end
        isempty(_nv_store) || @printf("[NV] Loaded %d entries from %s\n",
                                       length(_nv_store), NV_FILE)
    catch e
        @printf("[NV] Warning: could not read store: %s\n", e)
    end
end

#-------------------------------------------------------------------------------
# Stack helpers  (SP = R26 by convention)
#-------------------------------------------------------------------------------

function stack_push!(cpu::CPU, val::Vector{Trit})
    sp = Int(clamp(_int(get_reg(cpu, SP_REG)), 1, length(cpu.memory)))
    sp -= REG_WIDTH
    sp < 1 && (println("[STACK] Stack overflow!"); return)
    set_reg!(cpu, SP_REG, _sat(sp))
    write_word!(cpu.memory, sp, val)
end

function stack_pop!(cpu::CPU)::Vector{Trit}
    sp = Int(clamp(_int(get_reg(cpu, SP_REG)), 1, length(cpu.memory)))
    sp > length(cpu.memory) - REG_WIDTH + 1 && (println("[STACK] Stack underflow!"); return fill(Zero, REG_WIDTH))
    val = read_word(cpu.memory, sp)
    set_reg!(cpu, SP_REG, _sat(sp + REG_WIDTH))
    val
end

#-------------------------------------------------------------------------------
# Execute one instruction
#-------------------------------------------------------------------------------

function execute!(cpu::CPU; receptor::Union{ReceptorInterface,Nothing}=nothing)
    opcode, dst, src1, src2, src3, lane, flags, sub, imm = decode_instruction(cpu)
    imm_int  = _int(imm)
    imm_addr = Int(clamp(imm_int, 1, length(cpu.memory)))

    # ── System Control ────────────────────────────────────────────────────────

    if opcode == OP_NOP
        # nothing

    elseif opcode == OP_HALT
        cpu.running = false; return

    elseif opcode == OP_RESET
        cpu.pc       = 1
        cpu.regs     = [fill(Zero, REG_WIDTH) for _ in 1:(N_REGS-1)]
        cpu.status   = Zero
        cpu.running  = true
        cpu.int_flag = Neg
        cpu.ivec_base = 0
        println("[RESET] Registers and PC cleared.")
        return

    elseif opcode == OP_PRINT
        r = get_reg(cpu, dst)
        @printf("R%d = %s  (%s)\n", dst, trits_to_string(r), string(_int(r)))

    elseif opcode == OP_DUMP
        println("── DUMP ─────────────────────────────────────────────────────────")
        @printf("PC=%d  STATUS=%s\n", cpu.pc, TRIT_SYMBOL[cpu.status])
        for i in 1:(N_REGS-1)
            r = cpu.regs[i]
            @printf("R%-2d = %s  (%s)\n", i, trits_to_string(r), string(_int(r)))
        end
        println("─────────────────────────────────────────────────────────────────")

    elseif opcode == OP_PRINTI
        println(string(imm_int))

    elseif opcode == OP_PRINTB
        r    = get_reg(cpu, dst)
        base = Int(imm_int)
        @printf("R%d = %s  ", dst, string(_int(r)))
        if     base == 9;  print_base9(r)
        elseif base == 12; print_base12(r)
        elseif base == 27; print_base27(r)
        elseif base == 60; print_base60(r)
        elseif base == 81; print_base81(r)
        else;  @printf("PRINTB: unsupported base %d\n", base); end

    elseif opcode == OP_PRINTS
        addr  = Int(clamp(_int(get_reg(cpu, dst)), 1, length(cpu.memory)))
        chars = Char[]
        while addr >= 1 && addr <= length(cpu.memory) - 2
            v = _int(cpu.memory[addr:addr+2])
            v == 0 && break
            push!(chars, Char(Int(v))); addr += 3
        end
        println(join(chars))

    # ── Compare & Branch ──────────────────────────────────────────────────────

    elseif opcode == OP_CMP
        diff = saturating_add_vec(get_reg(cpu, src1), tritwise_not(get_reg(cpu, src2)))
        set_status!(cpu, diff)

    elseif opcode == OP_CMPI
        diff = saturating_add_vec(get_reg(cpu, src1), _sat(-imm_int))
        set_status!(cpu, diff)

    elseif opcode == OP_MIN
        a = get_reg(cpu, src1); b = get_reg(cpu, src2)
        val = _int(a) <= _int(b) ? a : b
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_MAX
        a = get_reg(cpu, src1); b = get_reg(cpu, src2)
        val = _int(a) >= _int(b) ? a : b
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_JMP;  cpu.pc = imm_addr; return
    elseif opcode == OP_JEZ;  cpu.status == Zero && (cpu.pc = imm_addr; return)
    elseif opcode == OP_JNZ;  cpu.status != Zero && (cpu.pc = imm_addr; return)
    elseif opcode == OP_JGT;  cpu.status == Pos  && (cpu.pc = imm_addr; return)
    elseif opcode == OP_JLT;  cpu.status == Neg  && (cpu.pc = imm_addr; return)
    elseif opcode == OP_JGEZ; cpu.status != Neg  && (cpu.pc = imm_addr; return)
    elseif opcode == OP_JLEZ; cpu.status != Pos  && (cpu.pc = imm_addr; return)

    # ── Shift & Rotate ────────────────────────────────────────────────────────

    elseif opcode == OP_LSHIFT
        val = shift_left_tryte(get_reg(cpu, src1))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_RSHIFT
        val = shift_right_tryte(get_reg(cpu, src1))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_LSHIFTN
        n   = abs(Int(clamp(_int(get_reg(cpu, src2)), -REG_WIDTH, REG_WIDTH)))
        val = shift_left_tryte(get_reg(cpu, src1), n)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_RSHIFTN
        n   = abs(Int(clamp(_int(get_reg(cpu, src2)), -REG_WIDTH, REG_WIDTH)))
        val = shift_right_tryte(get_reg(cpu, src1), n)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_ROTL
        val = rotate_left_tryte(get_reg(cpu, src1))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_ROTR
        val = rotate_right_tryte(get_reg(cpu, src1))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    # ── Extended Kleene Logic ─────────────────────────────────────────────────

    elseif opcode == OP_TNOT
        val = tritwise_not(get_reg(cpu, src1))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TNAND
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tNAND, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TNOR
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tNOR,  REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TXNOR
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tXNOR, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TIMP
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tIMP,  REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TMUX
        a = get_reg(cpu, src1); b = get_reg(cpu, src2)
        val = cpu.status == Pos  ? a :
              cpu.status == Zero ? b : tritwise_not(a)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TMAJ
        # src3 is a native Segment-B field — no imm-field hack required
        val = tMAJ3(get_reg(cpu, src1), get_reg(cpu, src2), get_reg(cpu, src3))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TCONS
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tCONS, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    # ── Arithmetic & Logic ────────────────────────────────────────────────────

    elseif opcode == OP_TXOR
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tXOR, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TXORI
        val = tritwise_gate(get_reg(cpu, src1), _sat(imm_int), tXOR, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TOR
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tOR, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TORI
        val = tritwise_gate(get_reg(cpu, src1), _sat(imm_int), tOR, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TAND
        val = tritwise_gate(get_reg(cpu, src1), get_reg(cpu, src2), tAND, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_TANDI
        val = tritwise_gate(get_reg(cpu, src1), _sat(imm_int), tAND, REG_WIDTH)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_DIV
        result, divzero = divide_trytes(get_reg(cpu, src1), get_reg(cpu, src2))
        if divzero
            cpu.status = Neg
            @printf("DIV/0: R%d unchanged, status set to Neg\n", dst)
        else
            val = _sat(_int(result))
            set_reg!(cpu, dst, val); set_status!(cpu, val)
        end

    elseif opcode == OP_DIVI
        imm_int == 0 && (cpu.status = Neg; @printf("DIVI/0: R%d unchanged\n", dst);
                         cpu.pc += INSTR_LEN; return)
        val = _sat(div(_int(get_reg(cpu, src1)), imm_int))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_MOD
        result, divzero = mod_trytes(get_reg(cpu, src1), get_reg(cpu, src2))
        if divzero
            cpu.status = Neg
            @printf("MOD/0: R%d unchanged, status set to Neg\n", dst)
        else
            val = _sat(_int(result))
            set_reg!(cpu, dst, val); set_status!(cpu, val)
        end

    elseif opcode == OP_MODI
        imm_int == 0 && (cpu.status = Neg; cpu.pc += INSTR_LEN; return)
        val = _sat(rem(_int(get_reg(cpu, src1)), imm_int))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_MUL
        val = _sat(_int(multiply_trytes(get_reg(cpu, src1), get_reg(cpu, src2))))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_MULI
        val = _sat(_int(multiply_trytes(get_reg(cpu, src1), _sat(imm_int))))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_STORE
        write_word!(cpu.memory, imm_addr, get_reg(cpu, src1))

    elseif opcode == OP_STORER
        addr = Int(clamp(_int(get_reg(cpu, src2)), 1, length(cpu.memory)))
        write_word!(cpu.memory, addr, get_reg(cpu, src1))

    elseif opcode == OP_STOREI
        addr = Int(clamp(_int(get_reg(cpu, src1)), 1, length(cpu.memory)))
        write_word!(cpu.memory, addr, _sat(imm_int))

    elseif opcode == OP_LOAD
        val = read_word(cpu.memory, imm_addr)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_LOADI
        # Segment C (27-trit Triple) sign-extends into the full 81-trit register
        val = _sat(imm_int)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_LOADR
        addr = Int(clamp(_int(get_reg(cpu, src1)), 1, length(cpu.memory)))
        val  = read_word(cpu.memory, addr)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_MOV
        val = get_reg(cpu, src1)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_XCHG
        a = get_reg(cpu, dst); b = get_reg(cpu, src1)
        set_reg!(cpu, dst, b); set_reg!(cpu, src1, a)
        set_status!(cpu, b)

    elseif opcode == OP_ADD
        val = saturating_add_vec(get_reg(cpu, src1), get_reg(cpu, src2))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_ADDI
        val = saturating_add_vec(get_reg(cpu, src1), _sat(imm_int))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_SUB
        val = saturating_add_vec(get_reg(cpu, src1), tritwise_not(get_reg(cpu, src2)))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_SUBI
        val = saturating_add_vec(get_reg(cpu, src1), _sat(-imm_int))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_NEG
        val = tritwise_not(get_reg(cpu, src1))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_ABS
        val = abs_trytes(get_reg(cpu, src1))
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_INC
        val = saturating_add_vec(get_reg(cpu, dst), [Pos])
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_DEC
        val = saturating_add_vec(get_reg(cpu, dst), [Neg])
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_SIGN
        n   = _int(get_reg(cpu, src1))
        val = _sat(n > 0 ? 1 : n < 0 ? -1 : 0)
        set_reg!(cpu, dst, val); set_status!(cpu, val)

    elseif opcode == OP_SSET
        n = _int(get_reg(cpu, src1))
        cpu.status = n > 0 ? Pos : n < 0 ? Neg : Zero

    # ── Hardware Receptor ─────────────────────────────────────────────────────

    elseif opcode == OP_RECEP
        ch   = clamp(Int(imm_int), 0,
                     receptor !== nothing ? receptor.backend.n_channels - 1 : 0)
        trit = receptor !== nothing ?
               (s = sample!(receptor); ch+1 <= length(s) ? s[ch+1] : Zero) :
               rand([Neg, Zero, Pos])
        set_reg!(cpu, dst, _sat(Int(trit))); cpu.status = trit

    elseif opcode == OP_SENSE
        n_samp = max(1, Int(imm_int))
        trit = if receptor !== nothing
            for _ in 1:n_samp; sample!(receptor); end
            mv = majority_vote(receptor, n_samp); isempty(mv) ? Zero : mv[1]
        else; rand([Neg, Zero, Pos]); end
        set_reg!(cpu, dst, _sat(Int(trit))); cpu.status = trit

    elseif opcode == OP_SAMP_DB
        trit = receptor !== nothing ?
               (s = sample!(receptor); isempty(s) ? Zero : s[1]) :
               rand([Neg, Zero, Pos])
        r = get_reg(cpu, dst); r[1] = trit
        set_reg!(cpu, dst, r); cpu.status = trit

    elseif opcode == OP_SETTH_P
        if receptor !== nothing
            v = Float64(_int(get_reg(cpu, src1))) / 1000.0
            receptor.pos_threshold = v
            @printf("[SETTH_P] Positive threshold → %.4f V\n", v)
        end

    elseif opcode == OP_SETTH_N
        if receptor !== nothing
            v = Float64(_int(get_reg(cpu, src1))) / 1000.0
            receptor.neg_threshold = v
            @printf("[SETTH_N] Negative threshold → %.4f V\n", v)
        end

    elseif opcode == OP_RCLEAR
        if receptor !== nothing
            empty!(receptor.history); receptor.sample_count = 0
            println("[RCLEAR] Receptor history flushed.")
        end

    elseif opcode == OP_RSTAT
        if receptor !== nothing
            nc  = clamp(receptor.backend.n_channels, -13, 13)
            sc  = clamp(receptor.sample_count % 9841, -9841, 9841)
            set_reg!(cpu, dst, _sat(nc + sc * 27))
        end

    elseif opcode == OP_QUERY_I2C
        if receptor !== nothing && isa(receptor.backend, ADS1115Backend)
            ch  = clamp(Int(imm_int), 0, receptor.backend.n_channels - 1)
            v   = ads1115_read_channel(receptor.backend, ch)
            val = _sat(round(Int, v * 1000))
            set_reg!(cpu, dst, val); set_status!(cpu, val)
        end

    elseif opcode == OP_QUERY_SPI
        if receptor !== nothing && isa(receptor.backend, MCP3008Backend)
            ch  = clamp(Int(imm_int), 0, receptor.backend.n_channels - 1)
            v   = mcp3008_read_channel(receptor.backend, ch)
            val = _sat(round(Int, v * 1000))
            set_reg!(cpu, dst, val); set_status!(cpu, val)
        end

    elseif opcode == OP_WRITE_I2C
        # I2C wire protocol is inherently binary — binary ops here are necessary
        if receptor !== nothing && isa(receptor.backend, ADS1115Backend)
            reg  = clamp(Int(imm_int), 0, 3)
            ival = Int(clamp(_int(get_reg(cpu, src1)), -32768, 32767))
            buf  = UInt8[UInt8(reg), UInt8((ival >> 8) & 0xFF), UInt8(ival & 0xFF)]
            ccall(:write, Cssize_t, (Cint, Ptr{UInt8}, Csize_t),
                  receptor.backend.fd, buf, 3)
            @printf("[WRITE_I2C] reg=%d val=%d\n", reg, ival)
        end

    elseif opcode == OP_WRITE_SPI
        if receptor !== nothing && isa(receptor.backend, MCP3008Backend)
            reg  = clamp(Int(imm_int), 0, 7)
            ival = Int(clamp(_int(get_reg(cpu, src1)), -9841, 9841))
            @printf("[WRITE_SPI] reg=%d val=%d (config write, no-op on MCP3008)\n", reg, ival)
        end

    elseif opcode == OP_GPIO_READ
        if receptor !== nothing && isa(receptor.backend, GPIOBackend)
            ch  = clamp(Int(imm_int), 0, receptor.backend.n_channels - 1)
            vs  = read_voltages(receptor.backend)
            raw = round(Int, ch+1 <= length(vs) ? vs[ch+1] : 0.0)
            val = _sat(clamp(raw, -1, 1))
            set_reg!(cpu, dst, val); set_status!(cpu, val)
        end

    elseif opcode == OP_GPIO_WRITE
        # sysfs GPIO is a binary interface — unavoidably binary at this boundary
        if receptor !== nothing && isa(receptor.backend, GPIOBackend)
            trit_val = get_reg(cpu, src1)[1]
            pin      = Int(clamp(imm_int, 0, 200))
            level    = trit_val == Pos ? "1" : "0"
            try
                write("/sys/class/gpio/gpio$(pin)/value", level)
            catch e
                @printf("[GPIO_WRITE] pin=%d trit=%s (write failed: %s)\n",
                        pin, TRIT_SYMBOL[trit_val], e)
            end
            @printf("[GPIO_WRITE] pin=%d -> %s\n", pin, TRIT_SYMBOL[trit_val])
        end

    elseif opcode == OP_COHERE
        if receptor !== nothing && isa(receptor.backend, SimulatedBackend)
            receptor.backend.operator_coherence = clamp(Float64(imm_int) / 1000.0, 0.0, 1.0)
            @printf("[COHERE] xi -> %.3f\n", receptor.backend.operator_coherence)
        end

    elseif opcode == OP_ARRAY_N
        if receptor !== nothing && isa(receptor.backend, SimulatedBackend)
            receptor.backend.operator_n = max(1, Int(imm_int))
            @printf("[ARRAY_N] N -> %d\n", receptor.backend.operator_n)
        end

    elseif opcode == OP_GAIN
        if receptor !== nothing && isa(receptor.backend, SimulatedBackend)
            g   = operator_gain(receptor.backend)
            val = _sat(clamp(round(Int, g), -9841, 9841))
            set_reg!(cpu, dst, val); set_status!(cpu, val)
            @printf("[GAIN] xi^2*N^2 = %.2e -> R%d\n", g, dst)
        end

    else
        # ── v3.1: Stack & Subroutines ─────────────────────────────────────────

        if opcode == OP_PUSH
            stack_push!(cpu, get_reg(cpu, src1))

        elseif opcode == OP_POP
            val = stack_pop!(cpu)
            set_reg!(cpu, dst, val); set_status!(cpu, val)

        elseif opcode == OP_CALL
            stack_push!(cpu, _sat(cpu.pc + INSTR_LEN))
            cpu.pc = imm_addr; return

        elseif opcode == OP_RET
            target = _int(stack_pop!(cpu))
            cpu.pc = Int(clamp(target, 1, length(cpu.memory))); return

        elseif opcode == OP_INT_EN
            cpu.int_flag = Pos
            println("[INT] Interrupts enabled.")

        elseif opcode == OP_INT_DIS
            cpu.int_flag = Neg
            println("[INT] Interrupts disabled.")

        elseif opcode == OP_IVEC
            cpu.ivec_base = imm_addr
            @printf("[IVEC] Interrupt vector base → %d\n", cpu.ivec_base)

        elseif opcode == OP_IRET
            target = _int(stack_pop!(cpu))
            cpu.int_flag = Pos
            cpu.pc = Int(clamp(target, 1, length(cpu.memory))); return

        # ── v3.1: Indexed Addressing ──────────────────────────────────────────

        elseif opcode == OP_LOADX
            addr = Int(clamp(_int(get_reg(cpu, src1)) + imm_int, 1, length(cpu.memory)))
            val  = read_word(cpu.memory, addr)
            set_reg!(cpu, dst, val); set_status!(cpu, val)

        elseif opcode == OP_LOADRR
            addr = Int(clamp(_int(get_reg(cpu, src1)) + _int(get_reg(cpu, src2)),
                             1, length(cpu.memory)))
            val  = read_word(cpu.memory, addr)
            set_reg!(cpu, dst, val); set_status!(cpu, val)

        elseif opcode == OP_STOREX
            # src1=Rs (value to store), src2=Ra (base address), imm=offset
            addr = Int(clamp(_int(get_reg(cpu, src2)) + imm_int, 1, length(cpu.memory)))
            write_word!(cpu.memory, addr, get_reg(cpu, src1))

        elseif opcode == OP_STORERR
            addr = Int(clamp(_int(get_reg(cpu, src1)) + _int(get_reg(cpu, src2)),
                             1, length(cpu.memory)))
            write_word!(cpu.memory, addr, get_reg(cpu, dst))

        # ── v3.1: Trit Manipulation ───────────────────────────────────────────

        elseif opcode == OP_TGET
            pos = Int(clamp(imm_int, 0, REG_WIDTH - 1)) + 1   # 1-indexed
            t   = get_reg(cpu, src1)[pos]
            val = fill(Zero, REG_WIDTH); val[1] = t            # LST carries the trit
            set_reg!(cpu, dst, val); cpu.status = t

        elseif opcode == OP_TSET
            pos  = Int(clamp(imm_int, 0, REG_WIDTH - 1)) + 1
            base = copy(get_reg(cpu, src1))
            base[pos] = get_reg(cpu, src2)[1]                  # LST of src2
            set_reg!(cpu, dst, base); set_status!(cpu, base)

        elseif opcode == OP_TSWAP
            pos_a = Int(clamp(imm_int, 0, REG_WIDTH - 1)) + 1
            pos_b = Int(clamp(sub,     0, REG_WIDTH - 1)) + 1  # SUB field
            base  = copy(get_reg(cpu, src1))
            base[pos_a], base[pos_b] = base[pos_b], base[pos_a]
            set_reg!(cpu, dst, base); set_status!(cpu, base)

        # ── v3.1: Explicit Ternary Select ─────────────────────────────────────

        elseif opcode == OP_TSEL
            # TSEL Rd Rsel Ra Rb Rc
            # src1=Rsel, src2=Ra, src3=Rb, SUB encodes Rc index
            # Neg→Ra(src2), Zero→Rb(src3), Pos→Rc(rc_idx)
            rc_idx = Int(clamp(sub, 0, N_REGS - 1))
            sel    = _int(get_reg(cpu, src1))
            val    = sel < 0  ? get_reg(cpu, src2)   :   # Neg  → Ra
                     sel == 0 ? get_reg(cpu, src3)   :   # Zero → Rb
                                get_reg(cpu, rc_idx)      # Pos  → Rc
            set_reg!(cpu, dst, val); set_status!(cpu, val)

        # ── v3.1: Non-Volatile Memory ─────────────────────────────────────────

        elseif opcode == OP_NVLOAD
            val = nv_load!(Int(imm_int))
            set_reg!(cpu, dst, val); set_status!(cpu, val)
            @printf("[NV] Loaded key %d → R%d\n", Int(imm_int), dst)

        elseif opcode == OP_NVSTORE
            nv_store!(Int(imm_int), get_reg(cpu, src1))
            @printf("[NV] Stored R%d → key %d\n", src1, Int(imm_int))

        else
            @printf("Unknown opcode %d at pc=%d\n", opcode, cpu.pc)
        end
    end

    cpu.pc += INSTR_LEN
end

#-------------------------------------------------------------------------------
# Run loop
#-------------------------------------------------------------------------------

function run!(cpu::CPU, max_cycles::Int=100_000;
              receptor::Union{ReceptorInterface,Nothing}=nothing)
    cycles = 0
    while cpu.running &&
          cpu.pc >= 1 &&
          cpu.pc + INSTR_LEN - 1 <= length(cpu.memory) &&
          cycles < max_cycles
        execute!(cpu; receptor=receptor)
        cycles += 1
    end
    cycles >= max_cycles &&
        @printf("Warning: max_cycles (%d) reached without HALT\n", max_cycles)
end

#===============================================================================#
# TWO-PASS ASSEMBLER
#===============================================================================#

mutable struct AssemblyProgram
    code::Vector{Trit}
    labels::Dict{String,Int}   # label --> trit address (1-indexed)
end

# Register token "R0".."R9" --> integer 0 to 9
function _parse_reg(s::AbstractString)
    (length(s) >= 2 && uppercase(s[1]) == 'R') || error("Expected register, got: $s")
    n = tryparse(Int, s[2:end])
    n === nothing && error("Invalid register: $s")
    (0 <= n <= N_REGS-1) || error("Register must be R0 to R$(N_REGS-1), got: R$n")
    n
end

# Parse integer literal or label reference
function _parse_arg(s::AbstractString, labels::Dict{String,Int})
    n = tryparse(Int, s)
    n !== nothing && return n
    key = uppercase(s)
    haskey(labels, key) && return labels[key]
    error("Unknown argument or label: $s")
end

"""
    parse_assembly_line(line, labels, pc) --> Vector{Trit} or Nothing

Parses one line of Ternary-AL v2.0 assembly into a 27-trit instruction.
Accepts `String` or `SubString` (any `AbstractString`).
Inline comments (`;` to end of line) are stripped first.
Register tokens are "R0".."R9"; label references are resolved from `labels`.
"""
function parse_assembly_line(line::AbstractString,
                              labels::Dict{String,Int}=Dict{String,Int}(),
                              pc::Int=1)
    # Strip comments and normalise
    line  = uppercase(strip(replace(line, r";.*" => "")))
    parts = split(line)
    isempty(parts) && return nothing
    cmd   = parts[1]
    np    = length(parts) - 1   # number of arguments

    r(i)  = _parse_reg(parts[i+1])
    a(i)  = _parse_arg(parts[i+1], labels)

    try
        # ── Control ─────────────────────────────────────────────────────────
        cmd == "NOP"    && return assemble_instr(OP_NOP)
        cmd == "HALT"   && return assemble_instr(OP_HALT)
        cmd == "RESET"  && return assemble_instr(OP_RESET)
        cmd == "DUMP"   && return assemble_instr(OP_DUMP)
        cmd == "RCLEAR" && return assemble_instr(OP_RCLEAR)

        # ── Print / Debug ────────────────────────────────────────────────────
        cmd == "PRINT"   && np >= 1 && return assemble_instr(OP_PRINT,  r(1))
        cmd == "PRINTS"  && np >= 1 && return assemble_instr(OP_PRINTS, r(1))
        cmd == "PRINTI"  && np >= 1 && return assemble_instr(OP_PRINTI, 0, 0, 0; imm=a(1))
        cmd == "PRINTB"  && np >= 2 && return assemble_instr(OP_PRINTB, r(1), 0, 0; imm=a(2))

        # ── Data movement ────────────────────────────────────────────────────
        cmd == "LOAD"   && np >= 2 && return assemble_instr(OP_LOAD,   r(1), 0, 0; imm=a(2))
        cmd == "LOADI"  && np >= 2 && return assemble_instr(OP_LOADI,  r(1), 0, 0; imm=a(2))
        cmd == "LOADR"  && np >= 2 && return assemble_instr(OP_LOADR,  r(1), r(2))
        cmd == "STORE"  && np >= 2 && return assemble_instr(OP_STORE,  0, r(1), 0; imm=a(2))
        cmd == "STORER" && np >= 2 && return assemble_instr(OP_STORER, 0, r(1), r(2))
        cmd == "STOREI" && np >= 2 && return assemble_instr(OP_STOREI, 0, r(1), 0; imm=a(2))
        cmd == "MOV"    && np >= 2 && return assemble_instr(OP_MOV,    r(1), r(2))
        cmd == "XCHG"   && np >= 2 && return assemble_instr(OP_XCHG,   r(1), r(2))

        # ── Arithmetic ───────────────────────────────────────────────────────
        cmd == "ADD"  && np >= 3 && return assemble_instr(OP_ADD,  r(1), r(2), r(3))
        cmd == "ADDI" && np >= 3 && return assemble_instr(OP_ADDI, r(1), r(2), 0; imm=a(3))
        cmd == "SUB"  && np >= 3 && return assemble_instr(OP_SUB,  r(1), r(2), r(3))
        cmd == "SUBI" && np >= 3 && return assemble_instr(OP_SUBI, r(1), r(2), 0; imm=a(3))
        cmd == "MUL"  && np >= 3 && return assemble_instr(OP_MUL,  r(1), r(2), r(3))
        cmd == "MULI" && np >= 3 && return assemble_instr(OP_MULI, r(1), r(2), 0; imm=a(3))
        cmd == "DIV"  && np >= 3 && return assemble_instr(OP_DIV,  r(1), r(2), r(3))
        cmd == "DIVI" && np >= 3 && return assemble_instr(OP_DIVI, r(1), r(2), 0; imm=a(3))
        cmd == "MOD"  && np >= 3 && return assemble_instr(OP_MOD,  r(1), r(2), r(3))
        cmd == "MODI" && np >= 3 && return assemble_instr(OP_MODI, r(1), r(2), 0; imm=a(3))
        cmd == "INC"  && np >= 1 && return assemble_instr(OP_INC,  r(1))
        cmd == "DEC"  && np >= 1 && return assemble_instr(OP_DEC,  r(1))
        cmd == "NEG"  && np >= 2 && return assemble_instr(OP_NEG,  r(1), r(2))
        cmd == "ABS"  && np >= 2 && return assemble_instr(OP_ABS,  r(1), r(2))
        cmd == "SIGN" && np >= 2 && return assemble_instr(OP_SIGN, r(1), r(2))
        cmd == "SSET" && np >= 1 && return assemble_instr(OP_SSET, 0, r(1))
        cmd == "MIN"  && np >= 3 && return assemble_instr(OP_MIN,  r(1), r(2), r(3))
        cmd == "MAX"  && np >= 3 && return assemble_instr(OP_MAX,  r(1), r(2), r(3))

        # ── Ternary Logic ────────────────────────────────────────────────────
        cmd == "TAND"  && np >= 3 && return assemble_instr(OP_TAND,  r(1), r(2), r(3))
        cmd == "TANDI" && np >= 3 && return assemble_instr(OP_TANDI, r(1), r(2), 0; imm=a(3))
        cmd == "TOR"   && np >= 3 && return assemble_instr(OP_TOR,   r(1), r(2), r(3))
        cmd == "TORI"  && np >= 3 && return assemble_instr(OP_TORI,  r(1), r(2), 0; imm=a(3))
        cmd == "TXOR"  && np >= 3 && return assemble_instr(OP_TXOR,  r(1), r(2), r(3))
        cmd == "TXORI" && np >= 3 && return assemble_instr(OP_TXORI, r(1), r(2), 0; imm=a(3))
        cmd == "TNOT"  && np >= 2 && return assemble_instr(OP_TNOT,  r(1), r(2))
        cmd == "TNAND" && np >= 3 && return assemble_instr(OP_TNAND, r(1), r(2), r(3))
        cmd == "TNOR"  && np >= 3 && return assemble_instr(OP_TNOR,  r(1), r(2), r(3))
        cmd == "TXNOR" && np >= 3 && return assemble_instr(OP_TXNOR, r(1), r(2), r(3))
        cmd == "TIMP"  && np >= 3 && return assemble_instr(OP_TIMP,  r(1), r(2), r(3))
        # TMUX: status-implicit, only two register sources
        cmd == "TMUX"  && np >= 3 && return assemble_instr(OP_TMUX,  r(1), r(2), r(3))
        # TMAJ: third source register index in imm field
        cmd == "TMAJ"  && np >= 4 && return assemble_instr(OP_TMAJ,  r(1), r(2), r(3), r(4))
        cmd == "TCONS" && np >= 3 && return assemble_instr(OP_TCONS, r(1), r(2), r(3))

        # ── Shift & Rotate ───────────────────────────────────────────────────
        cmd == "LSHIFT"  && np >= 2 && return assemble_instr(OP_LSHIFT,  r(1), r(2))
        cmd == "RSHIFT"  && np >= 2 && return assemble_instr(OP_RSHIFT,  r(1), r(2))
        cmd == "LSHIFTN" && np >= 3 && return assemble_instr(OP_LSHIFTN, r(1), r(2), r(3))
        cmd == "RSHIFTN" && np >= 3 && return assemble_instr(OP_RSHIFTN, r(1), r(2), r(3))
        cmd == "ROTL"    && np >= 2 && return assemble_instr(OP_ROTL,    r(1), r(2))
        cmd == "ROTR"    && np >= 2 && return assemble_instr(OP_ROTR,    r(1), r(2))

        # ── Compare & Branch ─────────────────────────────────────────────────
        cmd == "CMP"  && np >= 2 && return assemble_instr(OP_CMP,  0, r(1), r(2))
        cmd == "CMPI" && np >= 2 && return assemble_instr(OP_CMPI, 0, r(1), 0; imm=a(2))
        cmd == "JMP"  && np >= 1 && return assemble_instr(OP_JMP,  0, 0, 0; imm=a(1))
        cmd == "JEZ"  && np >= 1 && return assemble_instr(OP_JEZ,  0, 0, 0; imm=a(1))
        cmd == "JNZ"  && np >= 1 && return assemble_instr(OP_JNZ,  0, 0, 0; imm=a(1))
        cmd == "JGT"  && np >= 1 && return assemble_instr(OP_JGT,  0, 0, 0; imm=a(1))
        cmd == "JLT"  && np >= 1 && return assemble_instr(OP_JLT,  0, 0, 0; imm=a(1))
        cmd == "JGEZ" && np >= 1 && return assemble_instr(OP_JGEZ, 0, 0, 0; imm=a(1))
        cmd == "JLEZ" && np >= 1 && return assemble_instr(OP_JLEZ, 0, 0, 0; imm=a(1))

        # ── Hardware Receptor ────────────────────────────────────────────────
        cmd == "RECEP"   && np >= 2 && return assemble_instr(OP_RECEP,   r(1), 0, 0; imm=a(2))
        cmd == "SENSE"   && np >= 2 && return assemble_instr(OP_SENSE,   r(1), 0, 0; imm=a(2))
        cmd == "SAMP_DB" && np >= 1 && return assemble_instr(OP_SAMP_DB, r(1))
        cmd == "SETTH_P" && np >= 1 && return assemble_instr(OP_SETTH_P, 0, r(1))
        cmd == "SETTH_N" && np >= 1 && return assemble_instr(OP_SETTH_N, 0, r(1))
        cmd == "RSTAT"   && np >= 1 && return assemble_instr(OP_RSTAT,   r(1))
        cmd == "COHERE"  && np >= 1 && return assemble_instr(OP_COHERE,  0, 0, 0; imm=a(1))
        cmd == "ARRAY_N" && np >= 1 && return assemble_instr(OP_ARRAY_N, 0, 0, 0; imm=a(1))
        cmd == "GAIN"    && np >= 1 && return assemble_instr(OP_GAIN,    r(1))

        # ── Hardware I/O (I²C / SPI / GPIO) ─────────────────────────────────
        cmd == "QUERY_I2C"  && np >= 2 && return assemble_instr(OP_QUERY_I2C,  r(1), 0, 0; imm=a(2))
        cmd == "WRITE_I2C"  && np >= 2 && return assemble_instr(OP_WRITE_I2C,  0, r(1), 0; imm=a(2))
        cmd == "QUERY_SPI"  && np >= 2 && return assemble_instr(OP_QUERY_SPI,  r(1), 0, 0; imm=a(2))
        cmd == "WRITE_SPI"  && np >= 2 && return assemble_instr(OP_WRITE_SPI,  0, r(1), 0; imm=a(2))
        cmd == "GPIO_READ"  && np >= 2 && return assemble_instr(OP_GPIO_READ,  r(1), 0, 0; imm=a(2))
        cmd == "GPIO_WRITE" && np >= 2 && return assemble_instr(OP_GPIO_WRITE, 0, r(1), 0; imm=a(2))

        # ── v3.1: Stack & Subroutines ────────────────────────────────────────
        # SP = R26 by convention; PUSH/POP use src1/dst; CALL/RET use imm/stack
        cmd == "PUSH"    && np >= 1 && return assemble_instr(OP_PUSH,    0, r(1))
        cmd == "POP"     && np >= 1 && return assemble_instr(OP_POP,     r(1))
        cmd == "CALL"    && np >= 1 && return assemble_instr(OP_CALL;    imm=a(1))
        cmd == "RET"               && return assemble_instr(OP_RET)
        cmd == "INT_EN"            && return assemble_instr(OP_INT_EN)
        cmd == "INT_DIS"           && return assemble_instr(OP_INT_DIS)
        cmd == "IVEC"    && np >= 1 && return assemble_instr(OP_IVEC;    imm=a(1))
        cmd == "IRET"              && return assemble_instr(OP_IRET)

        # ── v3.1: Indexed Addressing ─────────────────────────────────────────
        cmd == "LOADX"   && np >= 3 && return assemble_instr(OP_LOADX,   r(1), r(2), 0; imm=a(3))
        cmd == "LOADRR"  && np >= 3 && return assemble_instr(OP_LOADRR,  r(1), r(2), r(3))
        cmd == "STOREX"  && np >= 3 && return assemble_instr(OP_STOREX,  0, r(1), r(2); imm=a(3))
        cmd == "STORERR" && np >= 3 && return assemble_instr(OP_STORERR, r(1), r(2), r(3))

        # ── v3.1: Trit Manipulation ───────────────────────────────────────────
        # TGET  Rd Rs imm      — extract trit at imm from Rs into LST of Rd
        # TSET  Rd Ra Rb imm   — copy LST(Rb) into Ra at position imm → Rd
        # TSWAP Rd Rs imm sub  — swap trits imm and sub within Rs → Rd
        cmd == "TGET"    && np >= 3 && return assemble_instr(OP_TGET,  r(1), r(2), 0; imm=a(3))
        cmd == "TSET"    && np >= 4 && return assemble_instr(OP_TSET,  r(1), r(2), r(3); imm=a(4))
        cmd == "TSWAP"   && np >= 4 && return assemble_instr(OP_TSWAP, r(1), r(2), 0; sub=a(3), imm=a(4))

        # ── v3.1: Explicit Ternary Select ────────────────────────────────────
        # TSEL Rd Rsel Ra Rb Rc   — Rc index encoded in SUB field
        cmd == "TSEL"    && np >= 5 && return assemble_instr(OP_TSEL,  r(1), r(2), r(3), r(4); sub=r(5))

        # ── v3.1: Non-Volatile Memory ─────────────────────────────────────────
        cmd == "NVLOAD"  && np >= 2 && return assemble_instr(OP_NVLOAD,  r(1), 0, 0; imm=a(2))
        cmd == "NVSTORE" && np >= 2 && return assemble_instr(OP_NVSTORE, 0, r(1), 0; imm=a(2))

    catch e
        @printf("Assembler error: %s\n  in: %s\n", e, line)
        return nothing
    end

    @printf("Unknown mnemonic or wrong arity: %s\n", line)
    nothing
end

"""
    assemble_program(lines) --> AssemblyProgram

Two-pass assembler supporting labels (trailing ':') and inline ';' comments.
First pass collects label to trit_address mappings.
Second pass assembles instructions with all label references resolved.
"""
function assemble_program(lines::Vector{<:AbstractString})
    labels   = Dict{String,Int}()
    filtered = Tuple{Int,String}[]   # (original line number, stripped line)
    pc       = 1                     # running trit address counter

    # ── Pass 1: collect labels ────────────────────────────────────────────────
    for (lineno, raw) in enumerate(lines)
        line = uppercase(strip(replace(raw, r";.*" => "")))
        isempty(line) && continue
        if endswith(line, ':')
            label = String(strip(line[1:end-1]))   # String() avoids SubString key
            isempty(label) && continue
            labels[label] = pc
        else
            push!(filtered, (lineno, raw))
            pc += INSTR_LEN
        end
    end

    # ── Pass 2: assemble with resolved labels ─────────────────────────────────
    code = Trit[]
    for (lineno, raw) in filtered
        instr = parse_assembly_line(raw, labels, length(code) + 1)
        if instr isa Vector{Trit}
            append!(code, instr)
        else
            @printf("  at line %d: %s\n", lineno, strip(raw))
        end
    end

    AssemblyProgram(code, labels)
end

#===============================================================================#
# DEBUGGER & SANDBOX
#===============================================================================#

mutable struct Debugger
    last_regs::Vector{Vector{Trit}}
    trace::Bool
end
Debugger() = Debugger([fill(Zero, REG_WIDTH) for _ in 1:(N_REGS-1)], false)
update_last_regs!(dbg::Debugger, cpu::CPU) = (dbg.last_regs = deepcopy(cpu.regs))

function monitor(cpu::CPU, dbg::Debugger; receptor=nothing)
    op, dst, src1, src2, src3, lane, flags, sub, imm = decode_instruction(cpu)
    op_name = get(OPCODE_NAMES, op, "???($op)")
    println("\n── CPU STATE ──────────────────────────────────────────────────────────")
    @printf("PC=%d  STATUS=%s  INT=%s  IVEC=%d\n",
            cpu.pc, TRIT_SYMBOL[cpu.status],
            cpu.int_flag == Pos ? "EN" : cpu.int_flag == Zero ? "MASK" : "DIS",
            cpu.ivec_base)
    @printf("Next: %s (dst=%d src1=%d src2=%d src3=%d imm=%s)\n",
            op_name, dst, src1, src2, src3, string(_int(imm)))
    println("Reg  │ Value (trit string)                                            │ Decimal                        │ diff")
    println("─────┼───────────────────────────────────────────────────────────────┼────────────────────────────────┼──────")
    for i in 1:(N_REGS-1)
        r       = cpu.regs[i]
        old     = dbg.last_regs[i]
        changed = r != old
        dec     = _int(r)
        @printf(" R%-2d │ %s │ %30s │ %s\n",
                i, trits_to_string(r), string(dec), changed ? "(changed)" : "")
    end
    println("───────────────────────────────────────────────────────────────────────")
    receptor !== nothing && show_receptor_status(receptor)
end

const SANDBOX_HELP = """
Ternary-AL v3.0 -- Tesseract Machine -- Sandbox / Assembler Reference
════════════════════════════════════════════════════════════════════════
ARCHITECTURE
  Registers : R0..R26  (27 total; R0 = constant Zero, writes ignored)
  Word width : 81 trits (Tesseract)   range ±2.21×10³⁸
  Instr width: 81 trits (27-27-27 Tesseract layout)
  Imm range  : ±3,812,798,742,493  (27-trit Triple, Segment C)
  Memory     : flat trit array, word-addressed in 81-trit units

NOTATION
  Rn     : register R0..R26
  imm    : integer literal or label name  (Triple range)
  T/0/1  : trit symbols Neg/Zero/Pos in printed output
  status : single trit updated by most instructions

SYNTAX RULES
  • Operands are space-separated (no commas)
  • Inline comments: text after ';' is ignored
  • Labels: write LABEL: on its own line; reference by name in jumps
  • All mnemonics are case-insensitive

────────────────────────────────────────────────────────────────────────
DATA MOVEMENT
  LOAD   Rd imm        Rd = mem[imm]            (81-trit Tesseract word)
  LOADI  Rd imm        Rd = imm                 (sign-extends Triple imm to 81 trits)
  LOADR  Rd Rs         Rd = mem[Rs]             (indirect via register)
  STORE  Rs imm        mem[imm] = Rs
  STORER Rs Ra         mem[Ra]  = Rs            (indirect address)
  STOREI Rs imm        mem[Rs]  = imm
  MOV    Rd Rs         Rd = Rs
  XCHG   Rd Rs         Rd ↔ Rs

────────────────────────────────────────────────────────────────────────
ARITHMETIC  (all results saturate to ±2.21×10³⁸)
  ADD    Rd Ra Rb      Rd = Ra + Rb
  ADDI   Rd Ra imm     Rd = Ra + imm
  SUB    Rd Ra Rb      Rd = Ra − Rb
  SUBI   Rd Ra imm     Rd = Ra − imm
  MUL    Rd Ra Rb      Rd = Ra × Rb  (saturating)
  MULI   Rd Ra imm     Rd = Ra × imm
  DIV    Rd Ra Rb      Rd = Ra ÷ Rb  (div/0 → status Neg, Rd unchanged)
  DIVI   Rd Ra imm     Rd = Ra ÷ imm
  MOD    Rd Ra Rb      Rd = Ra mod Rb  (sign follows dividend)
  MODI   Rd Ra imm     Rd = Ra mod imm
  INC    Rd            Rd += 1
  DEC    Rd            Rd −= 1
  NEG    Rd Rs         Rd = −Rs  (tritwise NOT == arithmetic negation)
  ABS    Rd Rs         Rd = |Rs|
  SIGN   Rd Rs         Rd = sign(Rs)  (full 81-trit word: −1, 0, or +1)
  MIN    Rd Ra Rb      Rd = min(Ra, Rb)
  MAX    Rd Ra Rb      Rd = max(Ra, Rb)
  SSET   Rs            status = sign(Rs)  (no register write)

────────────────────────────────────────────────────────────────────────
TERNARY (KLEENE) LOGIC  (tritwise across all 81 trits)
  TAND   Rd Ra Rb      Rd = Ra AND Rb     (Kleene min)
  TANDI  Rd Ra imm     Rd = Ra AND imm
  TOR    Rd Ra Rb      Rd = Ra OR  Rb     (Kleene max)
  TORI   Rd Ra imm     Rd = Ra OR  imm
  TXOR   Rd Ra Rb      Rd = Ra XOR Rb
  TXORI  Rd Ra imm     Rd = Ra XOR imm
  TNOT   Rd Rs         Rd = NOT Rs        (T↔1, 0→0)
  TNAND  Rd Ra Rb      Rd = NOT(Ra AND Rb)
  TNOR   Rd Ra Rb      Rd = NOT(Ra OR  Rb)
  TXNOR  Rd Ra Rb      Rd = NOT(Ra XOR Rb)
  TIMP   Rd Ra Rb      Rd = Ra → Rb  (OR(NOT(Ra), Rb))
  TMUX   Rd Ra Rb      status-implicit: Pos→Ra, Zero→Rb, Neg→NOT Ra
  TMAJ   Rd Ra Rb Rc   Rd = majority(Ra,Rb,Rc)  (Rc is native Segment-B src3)
  TCONS  Rd Ra Rb      Rd = consensus(Ra,Rb)

────────────────────────────────────────────────────────────────────────
SHIFT & ROTATE
  LSHIFT   Rd Rs       Rd = Rs << 1 trit
  RSHIFT   Rd Rs       Rd = Rs >> 1 trit
  LSHIFTN  Rd Rs Rn    Rd = Rs << |Rn| trits
  RSHIFTN  Rd Rs Rn    Rd = Rs >> |Rn| trits
  ROTL     Rd Rs       rotate Rs left  1 trit
  ROTR     Rd Rs       rotate Rs right 1 trit

────────────────────────────────────────────────────────────────────────
COMPARE & BRANCH  (each instruction = 81 trits; instr N starts at 1+(N-1)*81)
  CMP    Ra Rb         status = sign(Ra − Rb)
  CMPI   Ra imm        status = sign(Ra − imm)
  JMP    imm           PC = imm  (unconditional)
  JEZ    imm           jump if status == Zero
  JNZ    imm           jump if status != Zero
  JGT    imm           jump if status == Pos
  JLT    imm           jump if status == Neg
  JGEZ   imm           jump if status != Neg  (≥ 0)
  JLEZ   imm           jump if status != Pos  (≤ 0)

────────────────────────────────────────────────────────────────────────
DEBUG / I/O
  PRINT  Rd            print Rd as 81-trit string and decimal
  PRINTI imm           print imm as decimal
  PRINTB Rd imm        print Rd in base imm  (9 / 12 / 27 / 60 / 81)
  PRINTS Rd            print null-terminated trit string at mem[Rd]
  DUMP                 print all R1..R26, status, PC
  NOP                  no operation
  HALT                 stop execution
  RESET                clear R1..R26, status, PC=1 (memory preserved)
  RCLEAR               flush receptor history buffer

────────────────────────────────────────────────────────────────────────
HARDWARE RECEPTOR
  RECEP    Rd imm      Rd = single sample from channel imm
  SENSE    Rd imm      Rd = majority vote of last imm samples (ch 0)
  SAMP_DB  Rd          Rd[LST] = dead-band state
  SETTH_P  Rs          positive threshold = Rs / 1000 (volts)
  SETTH_N  Rs          negative threshold = Rs / 1000 (volts)
  RSTAT    Rd          Rd = encoded (n_channels, sample_count)
  QUERY_I2C  Rd imm    Rd = ADS1115 channel imm voltage × 1000
  WRITE_I2C  Rs imm    write Rs to ADS1115 register imm
  QUERY_SPI  Rd imm    Rd = MCP3008 channel imm voltage × 1000
  WRITE_SPI  Rs imm    write Rs to MCP3008 config register imm
  GPIO_READ  Rd imm    Rd = GPIO pin imm trit state
  GPIO_WRITE Rs imm    write LST of Rs to GPIO pin imm
  COHERE   imm         set simulated ξ = imm / 1000
  ARRAY_N  imm         set simulated array size N = imm
  GAIN     Rd          Rd = ξ²N² (operator gain)

────────────────────────────────────────────────────────────────────────
SANDBOX COMMANDS
  run                  run until HALT or max_cycles
  step                 execute one instruction
  reset                clear R1..R26, status, PC=1 (memory preserved)
  monitor              show full CPU + receptor state
  status               show status trit and PC only
  trace [on|off]       toggle per-instruction trace
  memdump ADDR LEN     dump LEN Tesseract words from trit-address ADDR
  convert N            show decimal N in balanced-ternary + all encodings
  receptor             show receptor layer status
  help                 this message
  quit / exit
════════════════════════════════════════════════════════════════════════
"""

function sandbox(; receptor::Union{ReceptorInterface,Nothing}=nothing,
                   hardware_detect::Bool=true)
    if receptor === nothing && hardware_detect
        backend  = detect_hardware(; n_channels=4, verbose=true)
        receptor = ReceptorInterface(backend)
    end

    cpu = CPU()
    dbg = Debugger()
    nv_load_file!()
    println("\n=== Ternary-AL v3.0 Tesseract Machine -- Interactive Sandbox ===")
    println("Type 'help' for commands. Enter assembly to execute immediately.")
    monitor(cpu, dbg; receptor=receptor)

    while true
        print("\nT-AL> ")
        input_line = strip(readline())
        isempty(input_line) && continue

        try
            cmd   = lowercase(split(input_line)[1])
            parts = split(input_line)

            if cmd in ("quit", "exit")
                break

            elseif cmd == "help"
                print(SANDBOX_HELP)

            elseif cmd == "run"
                update_last_regs!(dbg, cpu)
                run!(cpu; receptor=receptor)
                monitor(cpu, dbg; receptor=receptor)

            elseif cmd == "step"
                update_last_regs!(dbg, cpu)
                execute!(cpu; receptor=receptor)
                if dbg.trace
                    op, _, _, _, _ = decode_instruction(cpu)
                    @printf("[TRACE] %s  pc=%d\n",
                            get(OPCODE_NAMES, op, "???"), cpu.pc)
                end
                monitor(cpu, dbg; receptor=receptor)

            elseif cmd == "monitor"
                monitor(cpu, dbg; receptor=receptor)

            elseif cmd == "status"
                @printf("PC=%d  STATUS=%s\n", cpu.pc, TRIT_SYMBOL[cpu.status])

            elseif cmd == "receptor"
                receptor !== nothing ? show_receptor_status(receptor) :
                                       println("No receptor attached.")

            elseif cmd == "trace"
                flag = length(parts) >= 2 ? lowercase(parts[2]) : ""
                dbg.trace = flag == "on" || (flag != "off" && !dbg.trace)
                @printf("Trace %s\n", dbg.trace ? "ON" : "OFF")

            elseif cmd == "reset"
                cpu.pc        = 1
                cpu.regs      = [fill(Zero, REG_WIDTH) for _ in 1:(N_REGS-1)]
                cpu.status    = Zero
                cpu.running   = true
                cpu.int_flag  = Neg
                cpu.ivec_base = 0
                println("CPU registers and PC reset. Memory preserved.")
                monitor(cpu, dbg; receptor=receptor)

            elseif cmd == "memdump"
                length(parts) < 3 && (println("Usage: memdump ADDR LEN"); continue)
                addr = parse(Int, parts[2]); len = parse(Int, parts[3])
                println("Mem dump from $addr, $len Tesseract word(s):")
                for i in 0:len-1
                    w   = read_word(cpu.memory, addr + i*REG_WIDTH)
                    dec = _int(w)
                    @printf("  [%5d] %s  (%s)\n", addr+i*REG_WIDTH, trits_to_string(w), string(dec))
                end

            elseif cmd == "convert"
                length(parts) < 2 && (println("Usage: convert N"); continue)
                n  = parse(Int, parts[2])
                tr = int_to_balanced(n, 9)
                @printf("Decimal %d  →  %s\n", n, trits_to_string(tr))
                print_all_bases(tr)

            else
                # Try to assemble and immediately execute as a single instruction
                instr = parse_assembly_line(input_line)
                if instr isa Vector{Trit}
                    load_program!(cpu, instr, cpu.pc)
                    update_last_regs!(dbg, cpu)
                    execute!(cpu; receptor=receptor)
                    monitor(cpu, dbg; receptor=receptor)
                else
                    println("Unknown command. Type 'help'.")
                end
            end

        catch e
            println("Error: $e")
        end
    end

    println("\n=== Analogue-Hermetic Environment Shut Down ===")
    receptor !== nothing && close_backend(receptor.backend)
end

#===============================================================================#
# RANDOMISED DEMONSTRATION
#===============================================================================#

"""
    demo(; seed=nothing)

Runs a full randomised showcase. Every call produces a distinct output.
Pass `seed=N` to replay a specific run exactly.
"""
function demo(; seed::Union{Int,Nothing}=nothing)
    actual_seed = something(seed, abs(rand(Int)))
    rng         = MersenneTwister(actual_seed)

    println("═══ Analogue-Hermetic Ternary Core v3.0 (Tesseract Machine) ═══")
    @printf("Seed: %d   │   Replay: demo(seed=%d)\n", actual_seed, actual_seed)
    @printf("Time: %s\n\n", Dates.format(now(), "yyyy-mm-dd HH:MM:SS"))

    #---------------------------------------------------------------------------
    # 1. Trit basics
    #---------------------------------------------------------------------------
    println("─── Trit states ───")
    tPRINT(Pos); tPRINT(Zero); tPRINT(Neg)

    #---------------------------------------------------------------------------
    # 2. Counter (randomised start, direction, step count)
    #---------------------------------------------------------------------------
    println("\n─── Trinity counter ───")
    start_val   = rand(rng, -50:50)
    step_count  = rand(rng, 3:12)
    going_up    = rand(rng, Bool)
    dir_str     = going_up ? "INC (+1)" : "DEC (−1)"
    @printf("Start=%d  Direction=%s  Steps=%d\n", start_val, dir_str, step_count)
    current = int_to_balanced(start_val, 9)
    for i in 1:step_count
        current = going_up ? increment_tryte(current) : decrement_tryte(current)
        # Re-clamp to 9 trits (carry can escape)
        current = int_to_balanced(clamp(balanced_ternary_to_int(current), -9841, 9841), 9)
        @printf("  Step %2d │ %7d │ %s\n",
                i, balanced_ternary_to_int(current), trits_to_string(current))
    end

    #---------------------------------------------------------------------------
    # 3. Kleene logic, 3 binary gates chosen at random
    #---------------------------------------------------------------------------
    println("\n─── Kleene logic (3 of 8 binary gates) ───")
    all_binary_gates = [
        ("TAND",  tAND),
        ("TOR",   tOR),
        ("TXOR",  tXOR),
        ("TNAND", tNAND),
        ("TNOR",  tNOR),
        ("TXNOR", tXNOR),
        ("TIMP",  tIMP),
        ("TCONS", tCONS),
    ]
    selected = shuffle(rng, all_binary_gates)[1:3]
    col_w    = 8
    header   = join(rpad(name, col_w) for (name, _) in selected)
    println("  x  y  │ $header")
    println("  ──────┼" * "─"^(col_w * 3))
    for x in [Neg, Zero, Pos], y in [Neg, Zero, Pos]
        sx = TRIT_SYMBOL[x]; sy = TRIT_SYMBOL[y]
        row = join(rpad(TRIT_SYMBOL[gate(x, y)], col_w) for (_, gate) in selected)
        println("  $sx  $sy  │ $row")
    end
    # Also show TNOT unary
    @printf("\n  TNOT:  T→%s  0→%s  1→%s\n",
            TRIT_SYMBOL[tNOT(Neg)], TRIT_SYMBOL[tNOT(Zero)], TRIT_SYMBOL[tNOT(Pos)])

    #---------------------------------------------------------------------------
    # 4. Saturating arithmetic (random operands)
    #---------------------------------------------------------------------------
    println("\n─── Tesseract saturating arithmetic ───")
    a_val = rand(rng, -9841:9841)
    b_val = rand(rng, -9841:9841)
    a_tri = int_to_balanced(a_val, REG_WIDTH)
    b_tri = int_to_balanced(b_val, REG_WIDTH)
    c_tri = saturating_add_vec(a_tri, b_tri)
    c_val = _int(c_tri)
    raw   = a_val + b_val
    saturated = raw != c_val
    @printf("  A = %7d  (%s)\n", a_val, trits_to_string(int_to_balanced(a_val, 9)))
    @printf("  B = %7d  (%s)\n", b_val, trits_to_string(int_to_balanced(b_val, 9)))
    @printf("  A+B raw = %d\n", raw)
    if saturated
        @printf("  A+B sat = %s  (saturated)\n", string(c_val))
    else
        @printf("  A+B     = %s\n", string(c_val))
    end
    neg_a = _int(tritwise_not(a_tri))
    abs_a = _int(abs_trytes(a_tri))
    @printf("  NEG(A)  = %s  (BT identity: tritwise NOT == arithmetic negate)\n", string(neg_a))
    @printf("  ABS(A)  = %s\n", string(abs_a))

    #---------------------------------------------------------------------------
    # 5. Multi-base encoding of a random Trinity value
    #---------------------------------------------------------------------------
    println("\n─── Multi-base encoding (random Trinity) ───")
    enc_val = rand(rng, -9841:9841)
    enc_tri = int_to_balanced(enc_val, 9)
    @printf("  Value: %d\n", enc_val)
    print_all_bases(enc_tri)

    #---------------------------------------------------------------------------
    # 6. Clock pulse / TritMemory
    #---------------------------------------------------------------------------
    println("\n─── Clock pulse / TritMemory ───")
    mem_cell = TritMemory(Zero)
    voltages = [rand(rng) * 3.0 - 1.5 for _ in 1:5]
    for v in voltages
        trit = clock_pulse!(mem_cell, v)
        @printf("  V=%+.3f → %s\n", v, TRIT_SYMBOL[trit])
    end

    #---------------------------------------------------------------------------
    # 7. Hardware receptor detection + coherence sweep
    #---------------------------------------------------------------------------
    println("\n─── Hardware receptor ───")
    backend  = detect_hardware(; n_channels=4, verbose=true)
    receptor = ReceptorInterface(backend)

    # Randomised coherence sweep, 4 (xi, N) pairs in ascending order
    raw_pairs = [(rand(rng, 0.0:0.05:1.0), rand(rng, [1, 4, 16, 64, 100, 256])) for _ in 1:4]
    pairs     = sort(raw_pairs, by=first)

    println("\n  Coherence sweep (random ξ, N pairs):")
    if isa(backend, SimulatedBackend)
        for (xi, n) in pairs
            backend.operator_coherence = xi
            backend.operator_n         = n
            g = operator_gain(backend)
            for _ in 1:max(5, n÷10); sample!(receptor); end
            mv = majority_vote(receptor, min(20, length(receptor.history)))
            @printf("  ξ=%4.2f  N=%4d  Gain=%8.2e  Vote: %s\n",
                    xi, n, g, join(TRIT_SYMBOL[t] for t in mv))
        end
    else
        for _ in 1:10; sample!(receptor); end
        println("  (Hardware backend, fixed coherence)")
    end
    show_receptor_status(receptor)
    close_backend(backend)

    #---------------------------------------------------------------------------
    # 8. CPU demo, procedurally generated program
    #---------------------------------------------------------------------------
    println("\n─── CPU demo: procedurally generated program ───")

    # Pick 2 to 3 random operands and a random operation
    n_operands  = rand(rng, 2:3)
    operands    = [rand(rng, -100:100) for _ in 1:n_operands]
    arith_ops   = [(OP_ADD, "ADD"), (OP_SUB, "SUB"), (OP_MUL, "MUL")]
    (op_code, op_name) = rand(rng, arith_ops)

    # Build program, loop counter: count from rand start, print each step
    loop_start  = rand(rng, -15:15)
    loop_bound  = rand(rng, 3:8)
    loop_limit  = loop_start + loop_bound
    # Trit address layout (all in 1-indexed trit space, INSTR_LEN=81):
    #   Instr 0  (addr   1): LOADI R1, operands[1]
    #   Instr 1  (addr  82): LOADI R2, operands[2]
    #   Instr 2  (addr 163): op    R3, R1, R2       (arithmetic result)
    #   Instr 3  (addr 244): LOADI R4, loop_start   (loop counter)
    #   Instr 4  (addr 325): LOADI R5, loop_limit
    #  [LOOP] addr 406:
    #   Instr 5  (addr 406): PRINT R4
    #   Instr 6  (addr 487): INC   R4
    #   Instr 7  (addr 568): CMP   R4, R5
    #   Instr 8  (addr 649): JEZ   exit_addr (811)
    #   Instr 9  (addr 730): JMP   406
    #  [EXIT] addr 811:
    #   Instr10  (addr 811): PRINT R3              (show arith result)
    #   Instr11  (addr 892): HALT

    loop_addr = 1 + 5 * INSTR_LEN    # 406
    exit_addr = 1 + 10 * INSTR_LEN   # 811

    program = vcat(
        assemble_instr(OP_LOADI, 1; imm=operands[1]),      # Instr 0
        assemble_instr(OP_LOADI, 2; imm=operands[2]),      # Instr 1
        assemble_instr(op_code,  3, 1, 2),                  # Instr 2
        assemble_instr(OP_LOADI, 4; imm=loop_start),        # Instr 3
        assemble_instr(OP_LOADI, 5; imm=loop_limit),        # Instr 4
        assemble_instr(OP_PRINT, 4),                         # Instr 5  [LOOP]
        assemble_instr(OP_INC,   4),                         # Instr 6
        assemble_instr(OP_CMP,   0, 4, 5),                   # Instr 7
        assemble_instr(OP_JEZ;   imm=exit_addr),             # Instr 8
        assemble_instr(OP_JMP;   imm=loop_addr),             # Instr 9
        assemble_instr(OP_PRINT, 3),                         # Instr10 [EXIT]
        assemble_instr(OP_HALT),                             # Instr11
    )

    @printf("  Operands: %s\n", join((string(o) for o in operands), ", "))
    @printf("  Operation: %s R3, R1, R2\n", op_name)
    expected = op_name == "ADD" ? operands[1] + operands[2] :
               op_name == "SUB" ? operands[1] - operands[2] :
                                  operands[1] * operands[2]
    @printf("  Expected R3 = %s (saturated to Tesseract range if needed)\n",
            string(clamp(BigInt(expected), -MAX_REG_VAL, MAX_REG_VAL)))
    @printf("  Loop: R4 from %d to %d (print each step)\n", loop_start, loop_limit)
    println("  -- Program output --")

    cpu = CPU()
    load_program!(cpu, program)
    run!(cpu; receptor=nothing)
    @printf("  CPU halted.  STATUS=%s\n", TRIT_SYMBOL[cpu.status])

    println("\n═══ End ═══")
end

#===============================================================================#
# MAIN
#===============================================================================#

function main()
    println("=== Analogue-Hermetic Ternary Core v2.0 ===")
    println("1) Run randomised demonstration")
    println("2) Interactive sandbox (hardware auto-detect)")
    println("3) Interactive sandbox (simulated receptors only)")
    println("4) Interactive sandbox (ADS1115 on I²C-1, addr 0x48)")
    println("5) Interactive sandbox (MCP3008 on SPI0.0)")
    println("6) Interactive sandbox (serial device)")
    println("7) Interactive sandbox (RPi5 GPIO digital threshold)")
    print("Choice (1 to 7, default 1): ")
    choice = strip(readline())

    if choice == "2"
        sandbox()

    elseif choice == "3"
        backend  = SimulatedBackend(n_channels=8)
        receptor = ReceptorInterface(backend)
        sandbox(; receptor=receptor, hardware_detect=false)

    elseif choice == "4"
        try
            backend  = ADS1115Backend(bus=1, address=UInt8(0x48), n_channels=4)
            receptor = ReceptorInterface(backend)
            sandbox(; receptor=receptor, hardware_detect=false)
        catch e
            println("ADS1115 init failed: $e. Falling back to simulated.")
            sandbox()
        end

    elseif choice == "5"
        try
            backend  = MCP3008Backend(bus=0, device=0, n_channels=8)
            receptor = ReceptorInterface(backend)
            sandbox(; receptor=receptor, hardware_detect=false)
        catch e
            println("MCP3008 init failed: $e. Falling back to simulated.")
            sandbox()
        end

    elseif choice == "6"
        print("Serial port [/dev/ttyUSB0]: ")
        port = strip(readline()); isempty(port) && (port = "/dev/ttyUSB0")
        print("Baud rate [115200]: ")
        baud_s = strip(readline())
        baud   = isempty(baud_s) ? 115200 : parse(Int, baud_s)
        try
            backend  = SerialBackend(port=port, baud=baud, n_channels=4)
            receptor = ReceptorInterface(backend)
            sandbox(; receptor=receptor, hardware_detect=false)
        catch e
            println("Serial init failed: $e. Falling back to simulated.")
            sandbox()
        end

    elseif choice == "7"
        println("Enter pin pairs (pos_pin,neg_pin) one per channel, blank line to finish.")
        pairs = Tuple{Int,Int}[]
        while true
            print("  CH$(length(pairs)) pos,neg: ")
            s = strip(readline()); isempty(s) && break
            p = split(s, ',')
            length(p) == 2 || (println("  Enter two comma-separated pin numbers."); continue)
            push!(pairs, (parse(Int, strip(p[1])), parse(Int, strip(p[2]))))
        end
        if isempty(pairs)
            println("No pins entered. Falling back to simulated.")
            sandbox()
        else
            try
                backend  = GPIOBackend(pairs)
                receptor = ReceptorInterface(backend)
                sandbox(; receptor=receptor, hardware_detect=false)
            catch e
                println("GPIO init failed: $e. Falling back to simulated.")
                sandbox()
            end
        end

    else
        demo()
    end
end

main()