"""
pwa.py - Biến web Flask thành PWA: cài lên màn hình chính điện thoại như một ứng dụng.

Dùng trong app.py (2 dòng):
    import pwa
    pwa.init_pwa(app)

Module này tự:
  * phục vụ /manifest.webmanifest, /sw.js (service worker), /offline
  * chèn vào MỌI trang HTML: manifest, theme-color, meta cho iOS, viewport (nếu trang thiếu),
    script đăng ký service worker và nút "Cài ứng dụng"
  => không cần sửa từng file template. (Nếu muốn gọn hơn, có thể dán các thẻ này vào layout chung.)

Lưu ý: trình duyệt chỉ cho cài PWA / chạy service worker khi trang chạy qua HTTPS
(hoặc localhost). Mở bằng http://IP-LAN trên điện thoại vẫn dùng được web bình thường nhưng
KHÔNG cài được - dùng ngrok / Cloudflare Tunnel / hosting để có HTTPS (xem HUONG_DAN_DIEN_THOAI.md).
"""
import json
from flask import Response, request, url_for

APP_NAME = "Trọ AI Đà Nẵng"
SHORT_NAME = "Trọ AI"
THEME = "#0f172a"
SW_VERSION = "v2"        # đổi số này khi muốn buộc điện thoại tải lại bộ nhớ đệm

SW_JS = r"""
const VERSION = '__VERSION__';
const STATIC_CACHE = 'tro-static-' + VERSION;
const PAGE_CACHE = 'tro-pages-' + VERSION;
const PRECACHE = ['/offline'];
// Không bao giờ cache: trang quản trị, đăng nhập, API và các hành động gửi dữ liệu
const NO_CACHE_PREFIX = ['/admin', '/login', '/logout', '/api/', '/bao-het', '/lien-he', '/danh-gia', '/phong/', '/sw.js'];
const CDN_HOSTS = ['cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'unpkg.com', 'fonts.googleapis.com', 'fonts.gstatic.com'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(STATIC_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => ![STATIC_CACHE, PAGE_CACHE].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  if (sameOrigin && NO_CACHE_PREFIX.some((p) => url.pathname.startsWith(p))) return;

  // Trang HTML: ưu tiên mạng (luôn mới nhất), mất mạng thì dùng bản đã lưu hoặc trang /offline
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok && sameOrigin) { const copy = res.clone(); caches.open(PAGE_CACHE).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || caches.match('/offline')))
    );
    return;
  }

  // CSS/JS/ảnh của chính web và thư viện CDN: dùng bản lưu trước, cập nhật ngầm
  if ((sameOrigin && url.pathname.startsWith('/static/')) || CDN_HOSTS.includes(url.hostname)) {
    e.respondWith(
      caches.open(STATIC_CACHE).then((cache) =>
        cache.match(req).then((cached) => {
          const network = fetch(req).then((res) => { if (res.ok || res.type === 'opaque') cache.put(req, res.clone()); return res; })
                                    .catch(() => cached);
          return cached || network;
        })
      )
    );
  }
  // Ô bản đồ OpenStreetMap, API... để trình duyệt tự xử lý
});
""".replace("__VERSION__", SW_VERSION)

OFFLINE_HTML = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Không có kết nối</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f172a;
color:#e2e8f0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;text-align:center;padding:24px}
h1{font-size:22px;margin:0 0 8px}p{color:#94a3b8;margin:0 0 20px}
button{background:#2563eb;color:#fff;border:0;border-radius:10px;padding:12px 22px;font-size:16px}</style></head>
<body><div><div style="font-size:48px">📡</div><h1>Bạn đang ngoại tuyến</h1>
<p>Không kết nối được tới Trọ AI Đà Nẵng. Kiểm tra Wi-Fi/4G rồi thử lại.</p>
<button onclick="location.reload()">Thử lại</button></div></body></html>"""

INSTALL_JS = """
<script>
(function () {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js').catch(function () {}); });
  }
  var standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone;
  if (standalone) return;
  var deferred = null, btn = null;
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function pill(text, onclick) {
    var b = document.createElement('button');
    b.type = 'button'; b.textContent = text;
    b.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:900;background:#2563eb;color:#fff;border:0;' +
      'border-radius:999px;padding:10px 16px;font:600 14px system-ui,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.35)';
    b.onclick = onclick; document.body.appendChild(b); return b;
  }
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault(); deferred = e;
    if (btn || load('pwaDismissed')) return;
    btn = pill('📲 Cài ứng dụng', function () {
      deferred.prompt();
      deferred.userChoice.then(function () { if (btn) btn.remove(); btn = null; deferred = null; });
    });
  });
  window.addEventListener('appinstalled', function () { if (btn) btn.remove(); btn = null; });
  // iPhone/iPad (Safari không có nút cài tự động): hướng dẫn thủ công 1 lần
  var ua = navigator.userAgent;
  var isIOS = /iphone|ipad|ipod/i.test(ua) && !/crios|fxios|edgios/i.test(ua);
  if (isIOS && !load('pwaDismissed')) {
    window.addEventListener('load', function () {
      var b = pill('📲 Cài lên iPhone: bấm Chia sẻ ⬆️ → "Thêm vào MH chính" (chạm để ẩn)', function () { store('pwaDismissed', '1'); b.remove(); });
      b.style.right = '12px'; b.style.borderRadius = '14px'; b.style.textAlign = 'left'; b.style.fontWeight = '500';
    });
  }
})();
</script>
"""


def _head_tags(has_viewport: bool) -> str:
    tags = [
        '<link rel="manifest" href="/manifest.webmanifest">',
        f'<meta name="theme-color" content="{THEME}">',
        '<meta name="mobile-web-app-capable" content="yes">',
        '<meta name="apple-mobile-web-app-capable" content="yes">',
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
        f'<meta name="apple-mobile-web-app-title" content="{SHORT_NAME}">',
        '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">',
        '<link rel="icon" type="image/png" sizes="32x32" href="/static/icons/favicon-32.png">',
    ]
    if not has_viewport:
        tags.insert(0, '<meta name="viewport" content="width=device-width, initial-scale=1">')
    return "\n".join(tags) + "\n"


def init_pwa(app):
    @app.route("/manifest.webmanifest")
    def pwa_manifest():
        manifest = {
            "name": APP_NAME, "short_name": SHORT_NAME,
            "description": "Gợi ý phòng trọ cho sinh viên tại Đà Nẵng: giá rẻ, bản đồ nhiệt, báo hết trọ.",
            "lang": "vi", "dir": "ltr",
            "start_url": "/?source=pwa", "scope": "/", "id": "/",
            "display": "standalone", "orientation": "portrait-primary",
            "background_color": THEME, "theme_color": THEME,
            "categories": ["lifestyle", "travel", "education"],
            "icons": [
                {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
            "shortcuts": [
                {"name": "Bản đồ nhiệt", "short_name": "Bản đồ", "url": "/ban-do-nhiet",
                 "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
            ],
        }
        return Response(json.dumps(manifest, ensure_ascii=False), mimetype="application/manifest+json")

    @app.route("/sw.js")
    def pwa_service_worker():
        resp = Response(SW_JS, mimetype="application/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/offline")
    def pwa_offline():
        return Response(OFFLINE_HTML, mimetype="text/html")

    @app.after_request
    def _inject_pwa(resp):
        """Chèn thẻ PWA + script vào mọi trang HTML (trừ các route của chính PWA)."""
        try:
            if (resp.mimetype != "text/html" or resp.status_code != 200 or resp.direct_passthrough
                    or "rel=\"manifest\"" in (resp.get_data(as_text=True)[:20000])):
                return resp
            html = resp.get_data(as_text=True)
            if "</head>" not in html or "</body>" not in html:
                return resp
            has_viewport = 'name="viewport"' in html or "name='viewport'" in html
            extra = ""
            if request.path.startswith("/admin"):     # trang quản trị: thêm CSS sửa lệch trên điện thoại
                extra = ('<link rel="stylesheet" href="/static/admin-mobile.css">\n'
                         '<script src="/static/admin-mobile.js" defer></script>\n')
            html = html.replace("</head>", _head_tags(has_viewport) + extra + "</head>", 1)
            idx = html.rfind("</body>")
            html = html[:idx] + INSTALL_JS + html[idx:]
            resp.set_data(html)
        except Exception:     # PWA chỉ là phần thêm: có lỗi gì cũng không được làm hỏng trang
            pass
        return resp