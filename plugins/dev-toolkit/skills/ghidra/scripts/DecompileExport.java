// Ghidra headless post-script: 全関数をデコンパイルして1ファイルに書き出す。
// usage: analyzeHeadless <proj> <name> -import x.dll -scriptPath . -postScript DecompileExport.java <out.c>
// @category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DecompileExport extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = args.length > 0 ? args[0] : "decomp.c";
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        PrintWriter w = new PrintWriter(new FileWriter(outPath));
        FunctionManager fm = currentProgram.getFunctionManager();
        int count = 0;
        for (Function func : fm.getFunctions(true)) {
            DecompileResults res;
            try { res = dec.decompileFunction(func, 90, monitor); }
            catch (Exception e) { continue; }
            if (res != null && res.decompileCompleted()) {
                w.println("// ======== " + func.getName() + "  @ " + func.getEntryPoint() + " ========");
                try { w.println(res.getDecompiledFunction().getC()); }
                catch (Exception e) { w.println("// (decompile text error)"); }
                w.println();
                count++;
            }
        }
        w.close();
        println("DECOMPILED_FUNCTIONS=" + count + " -> " + outPath);
    }
}
