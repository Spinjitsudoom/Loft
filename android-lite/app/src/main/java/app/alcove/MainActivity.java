package app.alcove;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

/**
 * Alcove Lite: the Alcove web app, opened at the server you pick.
 *
 * The first screen (assets/start.html) asks for the server's address and checks an Alcove
 * server answers there. After that the app opens straight onto it, where you sign in. Your
 * settings > This app > Change server (or the link on the sign-in page) comes back here.
 *
 * The app's own files are kept on the phone (ShellCache), so with no connection it still opens,
 * onto the books you've downloaded. The screen stays on while a book is open.
 */
public class MainActivity extends Activity {
    private static final String START = "file:///android_asset/start.html";
    private static final int PICK_FILES = 7;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private WebView web;
    private ValueCallback<Uri[]> picking;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#14110f"));
        setContentView(root);
        // Lets a computer with USB debugging inspect the page (chrome://inspect).
        WebView.setWebContentsDebuggingEnabled(true);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);   // and IndexedDB, where downloaded books are kept
        s.setAllowFileAccess(true);     // the start page
        s.setUserAgentString(s.getUserAgentString() + " AlcoveAndroid/" + version());
        CookieManager.getInstance().setAcceptCookie(true);
        web.setBackgroundColor(Color.parseColor("#14110f"));
        web.addJavascriptInterface(new Bridge(), "AlcoveAndroid");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        web.setDownloadListener(this::saveFile);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        if (state != null) web.restoreState(state);
        else openServer();
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("alcove", MODE_PRIVATE);
    }

    private String server() {
        return prefs().getString("server", null);
    }

    private void openServer() {
        String server = server();
        web.loadUrl(server == null ? START : server + "/");
    }

    private void showStart(String error) {
        web.loadUrl(error == null ? START : START + "#error=" + Uri.encode(error));
    }

    private boolean isServer(Uri uri) {
        String server = server();
        if (server == null || uri.getScheme() == null) return false;
        Uri s = Uri.parse(server);
        return s.getScheme().equals(uri.getScheme()) && s.getAuthority() != null && s.getAuthority().equals(uri.getAuthority());
    }

    /** Pages of the chosen server (and the start page) stay in the app; anything else goes to the browser. */
    private boolean isOurs(Uri uri) {
        return uri.toString().startsWith(START) || isServer(uri);
    }

    /** "Save file" on a book's page: Android's own downloads, signed in as you. */
    private void saveFile(String url, String userAgent, String disposition, String mime, long length) {
        if (!isServer(Uri.parse(url))) return;
        try {
            String name = URLUtil.guessFileName(url, disposition, mime);
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) r.addRequestHeader("Cookie", cookie);
            r.addRequestHeader("User-Agent", userAgent);
            r.setMimeType(mime);
            r.setTitle(name);
            r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(r);
            Toast.makeText(this, "Saving " + name + " to Downloads", Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, "That file couldn’t be saved", Toast.LENGTH_SHORT).show();
        }
    }

    /** Keep the screen on while a book is open (the reader's address is #/read/...). */
    private void readingChanged(String url) {
        boolean reading = url != null && url.contains("#/read/");
        if (reading) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        if (request != PICK_FILES || picking == null) { super.onActivityResult(request, result, data); return; }
        Uri[] chosen = null;
        if (result == RESULT_OK && data != null) {
            if (data.getClipData() != null) {
                chosen = new Uri[data.getClipData().getItemCount()];
                for (int i = 0; i < chosen.length; i++) chosen[i] = data.getClipData().getItemAt(i).getUri();
            } else if (data.getData() != null) {
                chosen = new Uri[] {data.getData()};
            }
        }
        picking.onReceiveValue(chosen);
        picking = null;
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }

    /** What the pages can ask of the phone, as window.AlcoveAndroid. */
    private class Bridge {
        /** Save the server address and open it. Only the start page may do this. */
        @JavascriptInterface
        public void setServer(final String url) {
            MAIN.post(() -> {
                String current = web.getUrl();
                if (current == null || !current.startsWith(START)) return;
                Uri u = Uri.parse(url);
                if (!"http".equals(u.getScheme()) && !"https".equals(u.getScheme())) return;
                if (u.getHost() == null) return;
                String clean = url.replaceAll("/+$", "");
                prefs().edit().putString("server", clean).apply();
                web.clearHistory();
                web.loadUrl(clean + "/");
            });
        }

        @JavascriptInterface
        public String getServer() {
            String s = server();
            return s == null ? "" : s;
        }

        /** Back to the start page, to pick another server. */
        @JavascriptInterface
        public void changeServer() {
            MAIN.post(() -> showStart(null));
        }

        @JavascriptInterface
        public String version() { return MainActivity.this.version(); }
    }

    private class Client extends WebViewClient {
        /** The web app's own files (not the books or the API): fetched as usual, and a copy kept
         * so with no connection the app still opens onto the downloaded books. */
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri uri = req.getUrl();
            if (!"GET".equals(req.getMethod()) || !isServer(uri)) return null;
            String path = uri.getPath() == null ? "/" : uri.getPath();
            if (path.startsWith("/api/")) return null;
            return ShellCache.fetch(getApplicationContext(), uri.toString(), path, req.getRequestHeaders());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            if (!req.isForMainFrame()) return false;
            return leave(req.getUrl());
        }

        /** Links to anywhere else open in the browser. */
        private boolean leave(Uri uri) {
            if (isOurs(uri)) return false;
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
            } catch (ActivityNotFoundException ignored) { }
            return true;
        }

        @Override
        public void doUpdateVisitedHistory(WebView view, String url, boolean reload) {
            readingChanged(url);
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (!req.isForMainFrame()) return;
            String url = req.getUrl().toString();
            if (url.startsWith(START)) return;
            String s = server();
            showStart("Couldn’t reach " + (s == null ? url : s.replaceFirst("^https?://", ""))
                + ". Check the server is running and that this phone is on the same network.");
        }
    }

    private class Chrome extends WebChromeClient {
        /** Choosing books to add or send, and pictures for covers. */
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (picking != null) picking.onReceiveValue(null);
            picking = callback;
            Intent i = new Intent(Intent.ACTION_GET_CONTENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            String[] types = params.getAcceptTypes();
            boolean images = types != null && types.length > 0 && types[0] != null && types[0].startsWith("image/");
            i.setType(images ? "image/*" : "*/*");  // books come as many kinds (EPUB, CBZ, MOBI...): any file
            i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
            try {
                startActivityForResult(Intent.createChooser(i, images ? "Choose a picture" : "Choose books"), PICK_FILES);
            } catch (ActivityNotFoundException e) {
                picking = null;
                return false;
            }
            return true;
        }
    }

    String version() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "?";
        }
    }
}
