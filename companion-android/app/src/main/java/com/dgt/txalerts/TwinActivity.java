package com.dgt.txalerts;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.TextView;

/**
 * Full-screen twin view for the tablet: the backend's live-simulation page (3D model, physics and anomaly injection)
 * in a WebView. The PC keeps running the model; this screen is the display and the controls.
 */
public class TwinActivity extends Activity {
    private WebView web;
    private TextView message;
    private Button retry;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#F2EFE6"));

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setBackgroundColor(Color.parseColor("#F2EFE6"));
        web.setWebViewClient(new WebViewClient() {
            @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) showError("Cannot reach the twin at " + url() + "\n" + e.getDescription()
                    + "\n\nCheck that the backend is running and that Tailscale is connected on this tablet.");
            }
            @Override public void onPageFinished(WebView v, String u) { hideError(); }
        });
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));

        message = new TextView(this);
        message.setTextColor(Color.parseColor("#1B1B18"));
        message.setTextSize(16);
        message.setPadding(48, 48, 48, 48);
        message.setVisibility(View.GONE);
        FrameLayout.LayoutParams mp = new FrameLayout.LayoutParams(-2, -2);
        mp.gravity = android.view.Gravity.CENTER;
        root.addView(message, mp);

        retry = new Button(this);
        retry.setText("Retry");
        retry.setVisibility(View.GONE);
        retry.setOnClickListener(v -> load());
        FrameLayout.LayoutParams rp = new FrameLayout.LayoutParams(-2, -2);
        rp.gravity = android.view.Gravity.CENTER_HORIZONTAL | android.view.Gravity.BOTTOM;
        rp.bottomMargin = 160;
        root.addView(retry, rp);

        setContentView(root);
        load();
    }

    private String url() { return Store.backend(this) + "/?view=tablet"; }

    private void load() {
        hideError();
        new Thread(() -> {
            String u = Store.resolve(this) + "/?view=tablet";
            runOnUiThread(() -> web.loadUrl(u));
        }, "resolve").start();
    }

    private void showError(String t) {
        message.setText(t);
        message.setVisibility(View.VISIBLE);
        retry.setVisibility(View.VISIBLE);
        web.setVisibility(View.INVISIBLE);
    }

    private void hideError() {
        message.setVisibility(View.GONE);
        retry.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
    }

    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) {                                  // immersive: the twin gets the whole screen
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }

    @Override protected void onPause() { web.onPause(); super.onPause(); }

    @Override protected void onResume() { super.onResume(); web.onResume(); }

    @Override protected void onDestroy() { web.destroy(); super.onDestroy(); }
}
