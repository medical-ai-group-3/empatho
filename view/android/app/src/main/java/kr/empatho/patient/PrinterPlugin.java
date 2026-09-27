package kr.empatho.patient;

import android.content.Context;
import android.print.PrintManager;
import android.webkit.WebView;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * 안내문 PDF 저장. 안드로이드 WebView 는 window.print() 를 무시한다 —
 * 웹에서는 되던 「PDF 저장」 단추가 앱에서는 아무 일도 안 했다.
 *
 * 그래서 안드로이드의 인쇄 창을 직접 연다. 거기서 「PDF 로 저장」을 고르면
 * 파일이 남는다. 인쇄할 모양은 웹과 같은 @media print (index.css 맨 아래)다.
 */
@CapacitorPlugin(name = "Printer")
public class PrinterPlugin extends Plugin {

    @PluginMethod
    public void print(PluginCall call) {
        String name = call.getString("name", "EMPATHO 안내문");
        getActivity().runOnUiThread(() -> {
            WebView web = getBridge().getWebView();
            PrintManager pm = (PrintManager) getActivity().getSystemService(Context.PRINT_SERVICE);
            pm.print(name, web.createPrintDocumentAdapter(name), null);
            call.resolve();
        });
    }
}
