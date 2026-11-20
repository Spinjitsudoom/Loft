package app.loft;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * Lends Android's installer the update Updater downloaded, for as long as it's been granted it.
 * Only files in the app's update folder can be read, and only by name; nothing can be written.
 */
public final class UpdateFiles extends ContentProvider {
    static final String FOLDER = "updates";

    static Uri uriFor(Context context, File file) {
        return Uri.parse("content://" + context.getPackageName() + ".updates/" + Uri.encode(file.getName()));
    }

    private File fileFor(Uri uri) throws FileNotFoundException {
        String name = uri.getLastPathSegment();
        if (name == null || !name.matches("loft-lite-[0-9.]+\\.apk")) throw new FileNotFoundException();
        File file = new File(new File(getContext().getCacheDir(), FOLDER), name);
        if (!file.isFile()) throw new FileNotFoundException();
        return file;
    }

    @Override public boolean onCreate() { return true; }

    @Override public String getType(Uri uri) { return "application/vnd.android.package-archive"; }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException();
        return ParcelFileDescriptor.open(fileFor(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public Cursor query(Uri uri, String[] p, String s, String[] a, String o) {
        try {
            File f = fileFor(uri);
            android.database.MatrixCursor c = new android.database.MatrixCursor(
                new String[]{android.provider.OpenableColumns.DISPLAY_NAME, android.provider.OpenableColumns.SIZE});
            c.addRow(new Object[]{f.getName(), f.length()});
            return c;
        } catch (FileNotFoundException e) {
            return null;
        }
    }

    @Override public Uri insert(Uri uri, ContentValues v) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String s, String[] a) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues v, String s, String[] a) { throw new UnsupportedOperationException(); }
}
