package app.loft;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;

/**
 * Keeping Loft Lite up to date from Loft's releases on GitHub.
 *
 * At most once a day, when the app comes to the front, it asks for the newest release. If there's
 * a newer Loft Lite it downloads it (it's small) into the app's own files, checks it against the
 * release's SHA256SUMS.txt, and asks: Install, or Later. Android never lets an app replace itself
 * silently, so Install opens Android's own installer; the first time, Android also asks the person
 * to let Loft install apps. Nothing about the library is sent.
 */
final class Updater {
    private static final String LATEST = "https://api.github.com/repos/Spinjitsudoom/Loft/releases/latest";
    private static final String RELEASES = "https://github.com/Spinjitsudoom/Loft/releases/latest";
    private static final long DAY = 24L * 60 * 60 * 1000;
    private static final int MAX_JSON = 2_000_000, MAX_APK = 50_000_000;

    private final Activity activity;
    private final SharedPreferences prefs;
    private final String current;
    private boolean busy;

    Updater(Activity activity, SharedPreferences prefs, String current) {
        this.activity = activity;
        this.prefs = prefs;
        this.current = current;
    }

    /** Check if a day has passed since the last time. */
    void checkIfDue() {
        long now = System.currentTimeMillis();
        if (busy || now - prefs.getLong("update_checked", 0) < DAY) return;
        busy = true;
        prefs.edit().putLong("update_checked", now).apply();
        new Thread(new Runnable() {
            public void run() {
                try { check(); } catch (Exception ignored) { /* offline: tomorrow */ } finally { busy = false; }
            }
        }, "loft-update").start();
    }

    static int[] parse(String v) {
        if (v == null) return null;
        String[] parts = v.trim().replaceFirst("^v", "").split("\\.");
        if (parts.length != 3) return null;
        try {
            return new int[]{Integer.parseInt(parts[0]), Integer.parseInt(parts[1]), Integer.parseInt(parts[2])};
        } catch (NumberFormatException e) {
            return null;
        }
    }

    static boolean newer(String candidate, String than) {
        int[] a = parse(candidate), b = parse(than);
        if (a == null || b == null) return false;
        for (int i = 0; i < 3; i++) if (a[i] != b[i]) return a[i] > b[i];
        return false;
    }

    private void check() throws Exception {
        JSONObject release = new JSONObject(new String(get(LATEST, MAX_JSON), "UTF-8"));
        if (release.optBoolean("draft") || release.optBoolean("prerelease")) return;
        final String version = release.optString("tag_name").replaceFirst("^v", "");
        if (!newer(version, current)) return;
        String name = "loft-lite-" + version + ".apk", apkUrl = null, sumsUrl = null;
        JSONArray assets = release.optJSONArray("assets");
        for (int i = 0; assets != null && i < assets.length(); i++) {
            JSONObject a = assets.getJSONObject(i);
            if (name.equals(a.optString("name"))) apkUrl = a.optString("browser_download_url");
            if ("SHA256SUMS.txt".equals(a.optString("name"))) sumsUrl = a.optString("browser_download_url");
        }
        if (apkUrl == null || sumsUrl == null || Build.VERSION.SDK_INT < 24) {
            ask(version, null);  // say it's out; the download page has it
            return;
        }
        String expected = null;
        for (String line : new String(get(sumsUrl, MAX_JSON), "UTF-8").split("\n")) {
            String[] parts = line.trim().split("\\s+");
            if (parts.length == 2 && parts[1].replaceFirst("^\\*", "").equals(name)) expected = parts[0].toLowerCase();
        }
        if (expected == null) return;
        byte[] apk = get(apkUrl, MAX_APK);
        if (!expected.equals(sha256(apk))) return;  // damaged or not ours: never offered
        File dir = new File(activity.getCacheDir(), UpdateFiles.FOLDER);
        File[] old = dir.listFiles();
        if (old != null) for (File f : old) f.delete();
        dir.mkdirs();
        File file = new File(dir, name);
        OutputStream out = new FileOutputStream(file);
        try { out.write(apk); } finally { out.close(); }
        ask(version, file);
    }

    private void ask(final String version, final File apk) {
        activity.runOnUiThread(new Runnable() {
            public void run() {
                if (activity.isFinishing()) return;
                AlertDialog.Builder b = new AlertDialog.Builder(activity)
                    .setTitle(apk != null ? "Loft " + version + " is ready to install" : "Loft " + version + " is out")
                    .setNegativeButton("Later", null);
                if (apk != null) {
                    b.setMessage("Android will ask you to confirm. Your downloaded books and settings stay as they are.")
                     .setPositiveButton("Install", (d, w) -> install(apk));
                } else {
                    b.setMessage("Get it from Loft's download page.")
                     .setPositiveButton("Download", (d, w) -> open(Uri.parse(RELEASES)));
                }
                b.show();
            }
        });
    }

    private void install(File apk) {
        Uri uri = UpdateFiles.uriFor(activity, apk);
        Intent intent = new Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            activity.startActivity(intent);
        } catch (ActivityNotFoundException e) {
            open(Uri.parse(RELEASES));
        }
    }

    private void open(Uri uri) {
        try { activity.startActivity(new Intent(Intent.ACTION_VIEW, uri)); } catch (ActivityNotFoundException ignored) { }
    }

    private byte[] get(String address, int limit) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(address).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        c.setRequestProperty("Accept", "application/vnd.github+json");
        c.setRequestProperty("User-Agent", "LoftAndroid/" + current);
        try {
            if (c.getResponseCode() != 200) throw new Exception("HTTP " + c.getResponseCode());
            InputStream in = c.getInputStream();
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            for (int n; (n = in.read(buf)) > 0; ) {
                out.write(buf, 0, n);
                if (out.size() > limit) throw new Exception("too big");
            }
            return out.toByteArray();
        } finally {
            c.disconnect();
        }
    }

    private static String sha256(byte[] data) throws Exception {
        StringBuilder hex = new StringBuilder();
        for (byte x : MessageDigest.getInstance("SHA-256").digest(data)) hex.append(String.format("%02x", x));
        return hex.toString();
    }
}
