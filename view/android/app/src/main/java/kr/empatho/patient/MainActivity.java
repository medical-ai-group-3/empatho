package kr.empatho.patient;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // 앱에만 있는 플러그인은 super.onCreate 전에 등록해야 브리지가 안다
        registerPlugin(PrinterPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
