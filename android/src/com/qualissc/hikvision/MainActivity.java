package com.qualissc.hikvision;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.DownloadListener;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {

    private static final String PREFS = "hikvision";
    private static final String KEY_URL = "server_url";

    private WebView web;

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String url = prefs().getString(KEY_URL, null);
        if (url == null || url.trim().length() == 0) {
            ecranConfiguration("Adresse du serveur, par exemple :\nhttp://192.168.88.80:8765");
        } else {
            afficherDashboard(url);
        }
    }

    private void ecranConfiguration(String message) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(56, 56, 56, 56);
        root.setBackgroundColor(Color.parseColor("#0f1720"));

        TextView titre = new TextView(this);
        titre.setText("Hikvision Monitor");
        titre.setTextColor(Color.parseColor("#e6edf3"));
        titre.setTextSize(24);
        titre.setGravity(Gravity.CENTER);
        root.addView(titre);

        TextView aide = new TextView(this);
        aide.setText(message);
        aide.setTextColor(Color.parseColor("#8b9bab"));
        aide.setTextSize(13);
        aide.setPadding(0, 20, 0, 20);
        root.addView(aide);

        final EditText champUrl = new EditText(this);
        champUrl.setHint("http://adresse:8765");
        champUrl.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        champUrl.setTextColor(Color.parseColor("#e6edf3"));
        champUrl.setHintTextColor(Color.parseColor("#5a6b7a"));
        champUrl.setSingleLine(true);
        root.addView(champUrl, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        final EditText champJeton = new EditText(this);
        champJeton.setHint("Jeton d'acces (DASHBOARD_TOKEN)");
        champJeton.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        champJeton.setTextColor(Color.parseColor("#e6edf3"));
        champJeton.setHintTextColor(Color.parseColor("#5a6b7a"));
        champJeton.setSingleLine(true);
        root.addView(champJeton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button bouton = new Button(this);
        bouton.setText("Se connecter");
        bouton.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                String u = champUrl.getText().toString().trim();
                if (u.length() == 0) { toast("L'adresse du serveur est obligatoire"); return; }
                if (!u.startsWith("http://") && !u.startsWith("https://")) u = "http://" + u;
                while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
                String jeton = champJeton.getText().toString().trim();
                prefs().edit().putString(KEY_URL, u).apply();
                afficherDashboard(jeton.length() == 0 ? u : u + "/?token=" + jeton);
            }
        });
        root.addView(bouton);

        setContentView(root);
    }

    private void afficherDashboard(String url) {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        web.setBackgroundColor(Color.parseColor("#0f1720"));
        web.setWebViewClient(new WebViewClient());
        web.setDownloadListener(new DownloadListener() {
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimetype, long contentLength) {
                try {
                    String nom = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimetype);
                    DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
                    r.addRequestHeader("X-Auth-Token", jetonMemorise());
                    r.setTitle(nom);
                    r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                    r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, nom);
                    ((DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(r);
                    toast("Telechargement : " + nom);
                } catch (Exception e) {
                    toast("Telechargement impossible : " + e.getMessage());
                }
            }
        });
        setContentView(web);
        web.loadUrl(url);
    }

    private String jetonMemorise() {
        return "";
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) { web.goBack(); return; }
        new AlertDialog.Builder(this)
            .setTitle("Hikvision Monitor")
            .setItems(new String[]{"Recharger", "Changer de serveur", "Quitter"},
                new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int choix) {
                        if (choix == 0 && web != null) {
                            web.reload();
                        } else if (choix == 1) {
                            prefs().edit().remove(KEY_URL).apply();
                            web = null;
                            ecranConfiguration("Nouvelle adresse du serveur :");
                        } else {
                            finish();
                        }
                    }
                })
            .show();
    }

    private void toast(String m) {
        Toast.makeText(this, m, Toast.LENGTH_LONG).show();
    }
}
