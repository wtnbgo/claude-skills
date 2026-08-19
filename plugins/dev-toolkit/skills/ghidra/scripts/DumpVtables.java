// Ghidra headless post-script: RTTI 由来の vftable シンボルと、その各スロットが指す
// 仮想関数(アドレス+名前)を書き出す。C++ クラスのメソッド→FUN_アドレス地図を得る用。
// usage: analyzeHeadless <proj> <name> -process x.dll -noanalysis -scriptPath . -postScript DumpVtables.java <out.txt>
// @category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DumpVtables extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter w = (args.length > 0) ? new PrintWriter(new FileWriter(args[0])) : null;
        SymbolTable st = currentProgram.getSymbolTable();
        Memory mem = currentProgram.getMemory();
        int psize = currentProgram.getDefaultPointerSize();
        SymbolIterator it = st.getAllSymbols(true);
        while (it.hasNext()) {
            Symbol s = it.next();
            String n = s.getName(true);
            if (!n.contains("vftable") || n.contains("meta_ptr")) continue;
            Address a = s.getAddress();
            emit(w, "VTABLE " + n + " @ " + a);
            for (int i = 0; i < 32; i++) {
                Address pa;
                long ptr;
                try {
                    pa = a.add((long) i * psize);
                    ptr = (psize == 8) ? mem.getLong(pa) : (mem.getInt(pa) & 0xffffffffL);
                } catch (Exception e) { break; }
                Address fa;
                try { fa = toAddr(ptr); } catch (Exception e) { break; }
                Function f = getFunctionContaining(fa);
                if (f == null) break; // vtable 終端 (関数ポインタでなくなった)
                emit(w, String.format("   +%-3x %s  %s", i * psize, fa.toString(), f.getName()));
            }
        }
        if (w != null) w.close();
        println("VTABLE_DUMP_DONE");
    }
    private void emit(PrintWriter w, String line) {
        if (w != null) w.println(line); else println(line);
    }
}
