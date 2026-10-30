# Top Kabda print bridge v2 — Windows / Chrome
# يعمل على 127.0.0.1:3210 فقط. يستقبل صورة الفاتورة (ESC/POS) من الموقع ويرسلها للطابعة:
#  - USB: عبر اسم الطابعة المثبتة في ويندوز (RAW) أو كصورة عبر تعريف الطابعة كبديل
#  - إيثرنت: مباشرة إلى IP والمنفذ 9100
import base64, io, ipaddress, json, socket, threading, traceback
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = '127.0.0.1', 3210
ALLOWED = {'https://hobe-1.github.io'}
try:
    import win32print, win32ui, win32con
    HAS_WIN32 = True
except Exception:
    HAS_WIN32 = False
    win32print = win32ui = win32con = None
try:
    from PIL import Image, ImageWin
    HAS_PIL = True
except Exception:
    HAS_PIL = False


def printer_list():
    if not HAS_WIN32:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = ''
    out = []
    for p in win32print.EnumPrinters(flags, None, 2):
        port = str(p.get('pPortName', ''))
        up = port.upper()
        kind = 'usb' if up.startswith('USB') else ('net' if up.startswith(('IP_', 'WSD', 'TCP', '192.', '10.')) or ':' in port else 'other')
        out.append({'name': p['pPrinterName'], 'port': port, 'kind': kind, 'default': p['pPrinterName'] == default})
    return out


def local_subnets():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80)); ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    return sorted({ip for ip in ips if not ip.startswith('127.')})


def probe(ip, port=9100, timeout=0.35):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return ip
    except Exception:
        return None


def discover():
    cands = ['127.0.0.1']
    for ip in local_subnets():
        net = ipaddress.ip_network(ip + '/24', strict=False)
        cands += [str(h) for h in net.hosts() if str(h) != ip]
    with ThreadPoolExecutor(max_workers=96) as ex:
        found = [r for r in ex.map(probe, cands) if r]
    return [{'ip': ip, 'port': 9100} for ip in found if ip != '127.0.0.1']


def tcp_send(ip, port, data):
    with socket.create_connection((ip, int(port or 9100)), timeout=5) as s:
        s.sendall(data)


def win_raw(name, data):
    h = win32print.OpenPrinter(name)
    try:
        win32print.StartDocPrinter(h, 1, ('TopKabda', None, 'RAW'))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


def win_image(name, png):
    # بديل لو رفض التعريف الطباعة الخام: نطبع الصورة عبر تعريف ويندوز
    if not HAS_PIL:
        raise RuntimeError('Pillow غير مثبت. شغّل install.bat')
    img = Image.open(io.BytesIO(png)).convert('RGB')
    dc = win32ui.CreateDC(); dc.CreatePrinterDC(name)
    try:
        dc.StartDoc('Top Kabda'); dc.StartPage()
        pw = dc.GetDeviceCaps(win32con.HORZRES)
        ph = int(img.height * pw / img.width)
        ImageWin.Dib(img).draw(dc.GetHandleOutput(), (0, 0, pw, ph))
        dc.EndPage(); dc.EndDoc()
    finally:
        dc.DeleteDC()


def send_one(p, escpos, png, copies):
    ip, name = str(p.get('ip') or '').strip(), str(p.get('n') or '').strip()
    names = {x['name'] for x in printer_list()}
    for _ in range(max(1, min(5, int(copies or 1)))):
        if name and name in names:
            try:
                win_raw(name, escpos)
            except Exception:
                if png: win_image(name, png)
                else: raise
        elif ip:
            tcp_send(ip, p.get('port') or 9100, escpos)
        else:
            raise RuntimeError('حدّد اسم طابعة ويندوز أو عنوان IP')
    return {'printer': name or ip, 'copies': copies}


class Handler(BaseHTTPRequestHandler):
    server_version = 'TopKabdaBridge/2.0'

    def _cors(self):
        o = self.headers.get('Origin', '')
        if o in ALLOWED:
            self.send_header('Access-Control-Allow-Origin', o)
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def send_json(self, status, data):
        b = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self._cors(); self.end_headers(); self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.send_header('Content-Length', '0'); self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0].rstrip('/')
        if path == '/health':
            return self.send_json(200, {'ok': True, 'service': 'TopKabdaBridge', 'win32': HAS_WIN32, 'pil': HAS_PIL})
        if path == '/printers':
            if not HAS_WIN32:
                return self.send_json(200, {'ok': False, 'error': 'pywin32 غير مثبت — شغّل install.bat', 'printers': []})
            try:
                return self.send_json(200, {'ok': True, 'printers': printer_list()})
            except Exception as e:
                return self.send_json(500, {'ok': False, 'error': str(e), 'printers': []})
        if path == '/discover':
            try:
                return self.send_json(200, {'ok': True, 'found': discover(), 'subnets': local_subnets()})
            except Exception as e:
                return self.send_json(500, {'ok': False, 'error': str(e), 'found': []})
        return self.send_json(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        o = self.headers.get('Origin', '')
        if o and o not in ALLOWED:
            return self.send_json(403, {'ok': False, 'error': 'origin not allowed'})
        if self.path.rstrip('/') != '/raw':
            return self.send_json(404, {'ok': False, 'error': 'not found'})
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n < 1 or n > 12_000_000:
                return self.send_json(400, {'ok': False, 'error': 'invalid body size'})
            d = json.loads(self.rfile.read(n).decode('utf-8'))
            esc = base64.b64decode(d.get('escpos') or '')
            png = base64.b64decode(d.get('png') or '') if d.get('png') else b''
            r = send_one(d.get('printer') or {}, esc, png, d.get('copies'))
            return self.send_json(200, {'ok': True, 'result': r})
        except Exception as e:
            return self.send_json(500, {'ok': False, 'error': str(e), 'trace': traceback.format_exc(limit=2)})

    def log_message(self, fmt, *a):
        print('[%s] %s' % (self.log_date_time_string(), fmt % a))


if __name__ == '__main__':
    print('Top Kabda Print Bridge v2: http://127.0.0.1:%d' % PORT)
    print('لا تغلق هذه النافذة أثناء الطباعة التلقائية.')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
