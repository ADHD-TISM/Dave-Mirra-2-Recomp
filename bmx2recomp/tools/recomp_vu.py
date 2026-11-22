"""recomp_vu.py <out.h> <vu1_HASH.bin>...  : VU1 micro code -> C (static recompile).

Input: VU1 micro memory snapshots written by the runtime with VU_RECORD=<dir>
(runtime/vu.c): vu1_<16 hex hash>.bin plus vu1_<hash>.pcs, the entry points
seen. Output: one header that runtime/vu.c includes.

Only pairs reachable from the entry points are generated: fall-through,
branch targets, BAL/JALR return points (pc + 16, which covers JR returns).
The E bit stops fall-through one pair later. A jump anywhere else lands in
the interpreter (vu_interp_state) with the branch/E state carried over.

Each pair is a VU_PAIR(...) line calling vu.c's own upper()/lower()/
upper_commit() with the instruction words as constants. Those are
always_inline, so clang folds the decode away while the behaviour stays the
interpreter's; VU_CHECK=1 at run time compares the two.
"""
import os, re, sys

def imm11(w):
    x = w & 0x7ff
    return x - 0x800 if x & 0x400 else x

def reachable(code, entries):
    npairs = len(code) // 8
    seen = set()
    work = [e & 0x3ff8 for e in entries]
    while work:
        pc = work.pop()
        while pc not in seen:
            seen.add(pc)
            lo = int.from_bytes(code[pc:pc + 4], 'little')
            hi = int.from_bytes(code[pc + 4:pc + 8], 'little')
            nxt = (pc + 8) & 0x3ff8
            if hi & 0x40000000:          # E bit: the next pair runs, then stop
                seen.add(nxt)
                break
            if not hi & 0x80000000:
                op = lo >> 25
                if op in (0x20, 0x21) or 0x28 <= op <= 0x2f:
                    work.append((pc + 8 + imm11(lo) * 8) & 0x3ff8)
                if op in (0x21, 0x25):   # BAL / JALR: returns to pc + 16
                    work.append((pc + 16) & 0x3ff8)
                if op in (0x20, 0x21, 0x24, 0x25):   # unconditional: delay slot, then gone
                    work.append(nxt)
                    break
            pc = nxt
    return seen

# ---- MAC/status flag liveness ------------------------------------------------
# An upper op's flag update is only needed if some path reaches a flag read
# before another flag update. The game's program reads the flags with FMAND
# and FSAND mask 0x002 (sign), both of which see only the latest update, so
# sticky status bits are not tracked. Conservative: a jump the analysis cannot
# follow (JR/JALR, a pair that was not generated, the end of a run) counts as
# a read. Writes must be exact (same rules as upper() in runtime/vu.c).
def upper_sets_flags(hi):
    fn = hi & 63
    if fn < 0x3c:
        if 0x10 <= fn <= 0x17 or fn in (0x1d, 0x1f, 0x2b, 0x2f): return False   # MAX/MINI
        return fn <= 0x2e
    op = ((hi >> 4) & 0x7c) | (hi & 3)
    if 0x10 <= op <= 0x17 or op in (0x1d, 0x1f, 0x2f): return False           # ITOF/FTOI, ABS, CLIP, NOP
    return op <= 0x2e and op not in (0x2b,)

INT_OPS = {0x04, 0x05, 0x08, 0x09, 0x24, 0x25, 0x28, 0x29, 0x2c, 0x2d, 0x2e, 0x2f}
def lower_reads_flags(lo, hi):
    if hi & 0x80000000: return False
    op = lo >> 25
    if op in (0x14, 0x16, 0x17, 0x18, 0x1a, 0x1b): return True           # FSEQ FSAND FSOR FMEQ FMAND FMOR
    is_, it = (lo >> 11) & 31, (lo >> 16) & 31
    if op in INT_OPS and (is_ in (16, 17) or it in (16, 17)): return True
    if op == 0x40:
        x = lo & 63
        if 0x30 <= x <= 0x35 and (is_ in (16, 17) or it in (16, 17)): return True
        if x >= 0x3c:
            x2 = ((lo >> 4) & 0x7c) | (lo & 3)
            if x2 in (0x3d, 0x3e, 0x3f) and (is_ in (16, 17) or it in (16, 17)): return True
    return False

def flag_liveness(code, live):
    """returns the set of pairs whose upper flag update must be kept"""
    def w(p, k): return int.from_bytes(code[p + 4 * k:p + 4 * k + 4], 'little')
    succ = {}
    for p in live:
        lo, hi = w(p, 0), w(p, 1)
        s = {(p + 8) & 0x3ff8}
        prev = (p - 8) & 0x3ff8
        unknown = False
        if prev in live:
            plo, phi = w(prev, 0), w(prev, 1)
            if not phi & 0x80000000:
                pop = plo >> 25
                if pop in (0x20, 0x21) or 0x28 <= pop <= 0x2f:
                    s.add((prev + 8 + imm11(plo) * 8) & 0x3ff8)       # p is the delay slot
                    if pop in (0x20, 0x21): s.discard((p + 8) & 0x3ff8)  # B/BAL: no fall-through (a BAL return comes back via JR = unknown)
                if pop in (0x24, 0x25): unknown = True                 # JR/JALR target unknown
            if phi & 0x40000000: unknown = True                        # p runs after an E bit: run ends
        if hi & 0x40000000: pass                                        # next pair still runs
        succ[p] = (s, unknown)
    lin = {p: False for p in live}      # least fixpoint: grow "live at entry" from the reads
    changed = True
    while changed:
        changed = False
        for p in live:
            s, unknown = succ[p]
            out = unknown or any((q not in live) or lin[q] for q in s)
            lo, hi = w(p, 0), w(p, 1)
            v = lower_reads_flags(lo, hi) or (out and not upper_sets_flags(hi))
            if v != lin[p]: lin[p] = v; changed = True
    keep = set()
    for p in live:
        s, unknown = succ[p]
        if unknown or any((q not in live) or lin[q] for q in s): keep.add(p)
    return keep

# ---- plain pairs --------------------------------------------------------------
# VU_PAIR keeps the branch delay slot and the E-bit stop at run time (bp, bt,
# ea). A pair needs none of that when it is no branch and has no E bit, and the
# pair before it in memory is no branch and has no E bit either: then bp is 0
# and ea is -1 when it runs (a jump resets bp after the delay slot), and it
# falls through to pc + 8. Such pairs use VU_PAIR_PLAIN. Not valid if an E bit
# sits in a branch delay slot (ea 0 would arrive by a jump): then none are plain.
def is_branch(lo, hi):
    if hi & 0x80000000: return False     # I bit: the lower word is an immediate
    op = lo >> 25
    return op in (0x20, 0x21, 0x24, 0x25) or 0x28 <= op <= 0x2f

def plain_pairs(code, live):
    def w2(p): return int.from_bytes(code[p:p + 4], 'little'), int.from_bytes(code[p + 4:p + 8], 'little')
    def special(p):
        lo, hi = w2(p)
        return is_branch(lo, hi) or bool(hi & 0x40000000)
    for p in live:
        lo, hi = w2(p)
        if hi & 0x40000000 and is_branch(*w2((p - 8) & 0x3ff8)): return set()
    return {p for p in live if not special(p) and not special((p - 8) & 0x3ff8)}

CHUNK = 64          # pairs per function
out = sys.argv[1]
snaps = sys.argv[2:]
lines = ['/* generated by tools/recomp_vu.py - do not edit */', '',
         'typedef struct { int ea, bp; u32 bt, next; u64 guard; } vu_rs;   /* pipeline state between chunks */', '']
table = []
for path in snaps:
    m = re.search(r'vu1_([0-9a-f]{16})\.bin$', os.path.basename(path))
    if not m:
        sys.exit(f'bad snapshot name {path}')
    h = m.group(1)
    code = open(path, 'rb').read()
    assert len(code) == 0x4000, path
    pcs_path = path[:-4] + '.pcs'
    entries = [int(x, 16) for x in open(pcs_path).read().split()] if os.path.exists(pcs_path) else [0]
    entries.append(0)
    live = reachable(code, entries)
    keepf = flag_liveness(code, live)
    plain = plain_pairs(code, live)
    nflag = sum(1 for q in live if upper_sets_flags(int.from_bytes(code[q + 4:q + 8], 'little')))
    npairs = len(code) // 8
    fn = f'vu1_rec_{h}'
    table.append((h, fn))
    lines.append(f'/* {len(live)} of {npairs} pairs reachable from entries {" ".join("%04x" % e for e in sorted(set(entries)))} */')
    # The program is split into chunks of about CHUNK pairs, one function each: a single
    # function of every pair took the compiler ~100 s (its loop passes grow faster than
    # the function). A jump out of a chunk returns to the dispatcher below with the
    # pipeline state (next, ea, bp, bt, guard) in a vu_rs.
    order = sorted(live)
    chunks = [order[i:i + CHUNK] for i in range(0, len(order), CHUNK)]
    owner = {}
    for c, ps in enumerate(chunks):
        for p in ps: owner[p] = c
    for c, ps in enumerate(chunks):
        mine = set(ps)
        lines.append(f'static int {fn}_{c}(vu_t *v, vu_rs *s) {{   /* {ps[0]:04x}-{ps[-1]:04x} */')
        lines.append('    static void *const L[%d] = {' % npairs)
        for i in range(0, npairs, 8):
            lines.append('        ' + ', '.join(f'&&p{(i + k) * 8:04x}' if (i + k) * 8 in mine else ('&&ex' if (i + k) * 8 in live else '&&fb')
                                               for k in range(8)) + ',')
        lines.append('    };')
        lines.append('    int ea = s->ea, bp = s->bp; u32 bt = s->bt, next = s->next; u64 guard = s->guard;')
        lines.append('    goto *L[(next & 0x3ff8) >> 3];')
        for k, p in enumerate(ps):
            lo = int.from_bytes(code[p:p + 4], 'little')
            hi = int.from_bytes(code[p + 4:p + 8], 'little')
            mac = 'VU_PAIR_PLAIN' if p in plain else 'VU_PAIR'
            lines.append(f'p{p:04x}: {mac}(0x{p:04x}u, 0x{lo:08x}u, 0x{hi:08x}u, {1 if p in keepf else 0});')
            nxt = (p + 8) & 0x3ff8
            following = ps[k + 1] if k + 1 < len(ps) else None
            if following != nxt:
                lines.append(f'    next = 0x{nxt:04x}u; goto *L[0x{nxt >> 3:x}];')
        lines.append('ex:')
        lines.append('    s->ea = ea; s->bp = bp; s->bt = bt; s->next = next; s->guard = guard; return 1;')
        lines.append('fb:')
        lines.append('    vu_rec_fallback(v, next, ea, bp, bt);')
        lines.append('out:')
        lines.append('    return 0;')
        lines.append('}')
    lines.append(f'static int (*const {fn}_chunk[{npairs}])(vu_t *, vu_rs *) = {{')
    for i in range(0, npairs, 8):
        lines.append('    ' + ', '.join(f'{fn}_{owner[(i + k) * 8]}' if (i + k) * 8 in owner else '0' for k in range(8)) + ',')
    lines.append('};')
    lines.append(f'static void {fn}(vu_t *v, u32 pc) {{')
    lines.append('    vu_rs s = { -1, 0, 0, pc, 0 };')
    lines.append('    for (;;) {')
    lines.append(f'        int (*f)(vu_t *, vu_rs *) = {fn}_chunk[(s.next & 0x3ff8) >> 3];')
    lines.append('        if (!f) { vu_rec_fallback(v, s.next, s.ea, s.bp, s.bt); return; }')
    lines.append('        if (!f(v, &s)) return;')
    lines.append('    }')
    lines.append('}')
    lines.append('')
    print(f'{h}: {len(plain)} plain pairs')
    print(f'{h}: {len(live)} of {npairs} pairs reachable; flag updates kept {sum(1 for q in live if q in keepf and upper_sets_flags(int.from_bytes(code[q + 4:q + 8], "little")))} of {nflag}')
lines.append('static const struct { u64 hash; void (*fn)(vu_t *, u32); } vu1_rec_table[] = {')
for h, fn in table:
    lines.append(f'    {{ 0x{h}ull, {fn} }},')
lines.append('    { 0, 0 }')
lines.append('};')
open(out, 'w').write('\n'.join(lines) + '\n')
print(f'{len(table)} VU1 program(s) -> {out}')
