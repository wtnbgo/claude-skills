#!/usr/bin/env python3
"""
フォールバック: DumpVtables.java がスロットを埋められない場合に、DLL/EXE の
生バイトから vtable の関数ポインタを直接読む。PE の ImageBase とセクション表を
正しく解釈するので RVA==ファイルオフセットでない実行体でも動く。

usage: read_vtables_from_dll.py <binary> <vtables.txt> [--methods prov|hand|N]
  <vtables.txt> は DumpVtables.java 出力 (行: "VTABLE <class>::vftable @ <hexVA>")。
  --methods: 仮想関数の並びラベル。
     prov = AddRef,Release,GetName,StartTransition (吉里吉里 TransHandlerProvider)
     hand = AddRef,Release,SetOption,StartProcess,EndProcess,Process,MakeFinalImage (同 Handler)
     N    = ラベルなしで N 個読む (既定 12)
"""
import sys, struct, re

def parse_pe(data):
    e_lfanew = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[e_lfanew:e_lfanew+4] == b'PE\0\0'
    coff = e_lfanew + 4
    machine, nsec = struct.unpack_from('<HH', data, coff)
    opt = coff + 20
    magic = struct.unpack_from('<H', data, opt)[0]
    if magic == 0x20b:  # PE32+
        image_base = struct.unpack_from('<Q', data, opt + 24)[0]; ptr = 8
    else:               # PE32
        image_base = struct.unpack_from('<I', data, opt + 28)[0]; ptr = 4
    opt_size = struct.unpack_from('<H', data, coff + 16)[0]
    sec_off = opt + opt_size
    secs = []
    for i in range(nsec):
        b = sec_off + i*40
        va = struct.unpack_from('<I', data, b+12)[0]
        raw = struct.unpack_from('<I', data, b+20)[0]
        vsz = struct.unpack_from('<I', data, b+8)[0]
        secs.append((va, vsz, raw))
    return image_base, ptr, secs

def va_to_off(va, image_base, secs):
    rva = va - image_base
    for (sva, vsz, raw) in secs:
        if sva <= rva < sva + max(vsz, 0x1000):
            return raw + (rva - sva)
    return None

def main():
    binf, vtf = sys.argv[1], sys.argv[2]
    mode = '12'
    if '--methods' in sys.argv:
        mode = sys.argv[sys.argv.index('--methods')+1]
    labels = {
        'prov': ['AddRef','Release','GetName','StartTransition'],
        'hand': ['AddRef','Release','SetOption','StartProcess','EndProcess','Process','MakeFinalImage'],
    }
    data = open(binf, 'rb').read()
    image_base, ptr, secs = parse_pe(data)
    for line in open(vtf):
        m = re.search(r'VTABLE\s+(\S+?)::vftable\s+@\s+([0-9a-fA-F]+)', line)
        if not m or 'meta_ptr' in line:
            continue
        cls, va = m.group(1), int(m.group(2), 16)
        if mode in labels:
            meths = labels[mode]
        elif 'Provider' in cls and 'prov' in labels:
            meths = labels['prov']
        else:
            meths = None
        n = len(meths) if meths else int(mode) if mode.isdigit() else 12
        off = va_to_off(va, image_base, secs)
        print(f"\n### {cls}  vftable@{va:x}")
        if off is None:
            print("   (vtable VA がセクションに解決できません)"); continue
        for i in range(n):
            p = struct.unpack_from('<I' if ptr==4 else '<Q', data, off + i*ptr)[0]
            # .text 範囲内かどうかで終端判定
            fo = va_to_off(p, image_base, secs)
            if fo is None:
                break
            label = meths[i] if meths and i < len(meths) else f"slot{i}"
            print(f"   +{i*ptr:<3x} FUN_{p:08x}  {label}")

if __name__ == '__main__':
    main()
