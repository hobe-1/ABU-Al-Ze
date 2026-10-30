# Top Kabda local print bridge for Windows / Chrome
# Listens only on loopback: http://127.0.0.1:3210
import json, os, socket, threading, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = '127.0.0.1', 3210
try:
    import win32print, win32ui, win32con
    from win32api import GetSystemMetrics
    HAS_WIN32 = True
except Exception:
    HAS_WIN32 = False
    win32print = win32ui = win32con = None


def printer_list():
    if not HAS_WIN32:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    out = []
    for p in win32print.EnumPrinters(flags):
        name = p[2]
        out.append({'name': name, 'default': bool(p[attributes_index()] & win32print.PRINTER_ATTRIBUTE_DEFAULT) if len(p) > attributes_index() else False})
    try:
        default = win32print.GetDefaultPrinter()
        for p in out: p['default'] = p['name'] == default
    except Exception:
        pass
    return out


def attributes_index():
    # EnumPrinters(PRINTER_INFO_4) returns (flags, description, name, comment); no attributes.
    return 99


def order_lines(order, settings, kind="cashier"):
    shop = str(settings.get('shop') or 'بوفية توب كبدة')
    width = str(settings.get('width') or '80')
    rule = '=' * (42 if width != '58' else 30)
    lines = [shop, rule]
    if kind == 'kitchen':
        lines.append('تذكرة المطبخ - طلب #' + str(order.get('r', '')))
        if order.get('t') == 'من السيارة':
            lines += ['استلام سيارة', 'السيارة: ' + str(order.get('c') or ''), 'اللون: ' + str(order.get('l') or ''), 'اللوحة: ' + str(order.get('p') or '')]
        if order.get('n'): lines.append('العميل: ' + str(order.get('n')))
        if order.get('w'): lines.append('وقت الاستلام: ' + str(order.get('w')))
    else:
        lines.append('فاتورة - طلب #' + str(order.get('r', '')))
        if order.get('ts'): lines.append('وقت الطلب: ' + str(order.get('ts')))
        if order.get('t'): lines.append('الاستلام: ' + str(order.get('t')))
        if order.get('w'): lines.append('وقت الاستلام: ' + str(order.get('w')))
        if order.get('n'): lines.append('العميل: ' + str(order.get('n')))
        if order.get('ph'): lines.append('الجوال: ' + str(order.get('ph')))
        if order.get('t') == 'من السيارة':
            lines += ['السيارة: ' + str(order.get('c') or ''), 'اللون: ' + str(order.get('l') or ''), 'اللوحة: ' + str(order.get('p') or '')]
    lines += ['-' * (42 if width != '58' else 30), 'الأصناف:']
    for item in order.get('i') or []:
        if isinstance(item, dict):
            name = item.get('name', item.get('n', 'صنف غير معروف'))
            qty = item.get('qty', item.get('q', 1))
            price = item.get('price', item.get('p', 0))
        elif isinstance(item, (list, tuple)):
            name = item[0] if len(item) > 0 else 'صنف غير معروف'
            qty = item[1] if len(item) > 1 else 1
            price = item[2] if len(item) > 2 else 0
        else:
            name, qty, price = str(item), 1, 0
        try: qty = float(qty or 0)
        except Exception: qty = 0.0
        try: price = float(price or 0)
        except Exception: price = 0
        qtxt = str(int(qty)) if qty.is_integer() else str(qty)
        lines.append(f'{qtxt} × {name}' + ('' if kind == 'kitchen' else f'   {qty*price:.2f} ر.س'))
    if order.get('no'): lines.append('ملاحظات: ' + str(order['no']))
    if kind != 'kitchen':
        try: disc = float(order.get('d') or 0)
        except Exception: disc = 0
        try: total = float(order.get('tot') or 0)
        except Exception: total = 0
        if disc: lines.append('الخصم: -%.2f ر.س' % disc)
        lines += [rule, 'الإجمالي: %.2f ر.س' % total]
        if settings.get('vatno'): lines.append('الرقم الضريبي: ' + str(settings['vatno']))
        if settings.get('foot'): lines.append(str(settings['foot']))
    lines += ['', '', '']
    return '\n'.join(lines)


def windows_print(printer_name, text):
    if not HAS_WIN32:
        raise RuntimeError('pywin32 غير مثبت. شغّل install.bat')
    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)
    try:
        dc.StartDoc('Top Kabda Receipt')
        dc.StartPage()
        caps = dc.GetDeviceCaps
        width = caps(win32con.HORZRES)
        height = caps(win32con.VERTRES)
        dpi = caps(win32con.LOGPIXELSY) or 203
        font = win32ui.CreateFont({'name': 'Arial', 'height': -max(16, int(dpi * 0.095)), 'weight': 500})
        dc.SelectObject(font)
        margin = max(8, int(dpi * 0.04))
        rect = (margin, margin, width - margin, height - margin)
        flags = win32con.DT_LEFT | win32con.DT_WORDBREAK | win32con.DT_NOPREFIX | win32con.DT_RTLREADING
        dc.DrawText(text, rect, flags)
        dc.EndPage()
        dc.EndDoc()
    finally:
        try: dc.DeleteDC()
        except Exception: pass


def raw_network_print(ip, port, text):
    # Raw ESC/POS fallback. Arabic code page differs by printer model; use installed Windows driver when available.
    payload = b'\x1b@' + b'\x1bt\x16' + text.encode('cp864', errors='replace') + b'\n\n\n\x1dV\x00'
    with socket.create_connection((ip, int(port or 9100)), timeout=4) as sock:
        sock.sendall(payload)


def print_one(printer, order, settings, default_name):
    role = str(printer.get('role') or 'both')
    kinds = ['cashier', 'kitchen'] if role == 'both' else [role if role in ('cashier', 'kitchen') else 'cashier']
    texts = [order_lines(order, settings, kind) for kind in kinds]
    name = str(printer.get('n') or '').strip()
    ip = str(printer.get('ip') or '').strip()
    port = int(printer.get('port') or 9100)
    names = {p['name'] for p in printer_list()}
    copies = max(1, min(5, int(printer.get('cp') or 1)))
    if name and name in names:
        for txt in texts:
            for _ in range(copies): windows_print(name, txt)
        return {'printer': name, 'method': 'windows-driver', 'copies': copies, 'jobs': kinds}
    if ip:
        for txt in texts:
            for _ in range(copies): raw_network_print(ip, port, txt)
        return {'printer': ip, 'method': 'tcp-9100', 'copies': copies, 'jobs': kinds, 'warning': 'قد يحتاج ترميز العربية ضبطاً حسب موديل الطابعة'}
    if default_name:
        for txt in texts:
            for _ in range(copies): windows_print(default_name, txt)
        return {'printer': default_name, 'method': 'windows-default', 'copies': copies, 'jobs': kinds}
    raise RuntimeError('لم يتم تحديد طابعة مثبتة في Windows أو عنوان IP صالح')


class Handler(BaseHTTPRequestHandler):
    server_version = 'TopKabdaPrintBridge/1.0'
    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        origin = self.headers.get('Origin', '')
        if origin == 'https://hobe-1.github.io': self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self.send_json(200, {'ok': True})
    def do_GET(self):
        if self.path.rstrip('/') == '/printers':
            if not HAS_WIN32: return self.send_json(200, {'ok': False, 'error': 'pywin32 غير مثبت', 'printers': []})
            try: return self.send_json(200, {'ok': True, 'printers': printer_list(), 'defaultPrinter': win32print.GetDefaultPrinter()})
            except Exception as e: return self.send_json(500, {'ok': False, 'error': str(e), 'printers': []})
        if self.path.rstrip('/') == '/health': return self.send_json(200, {'ok': True, 'service': 'TopKabdaPrintBridge', 'port': PORT, 'win32': HAS_WIN32})
        return self.send_json(404, {'ok': False, 'error': 'not found'})
    def do_POST(self):
        origin = self.headers.get('Origin', '')
        if origin and origin != 'https://hobe-1.github.io': return self.send_json(403, {'ok': False, 'error': 'origin not allowed'})
        if self.path.rstrip('/') != '/print': return self.send_json(404, {'ok': False, 'error': 'not found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 2_000_000: return self.send_json(400, {'ok': False, 'error': 'invalid body size'})
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            order = data.get('order') or {}; settings = data.get('settings') or {}
            printers = settings.get('printers') or []
            default_name = None
            if HAS_WIN32:
                try: default_name = win32print.GetDefaultPrinter()
                except Exception: pass
            chosen = []
            for p in printers:
                role = p.get('role', 'both')
                if role in ('both', 'cashier', 'kitchen'): chosen.append(p)
            if not chosen: chosen = [{'n': default_name or '', 'ip': '', 'port': 9100, 'role': 'both', 'cp': 1}]
            results = []
            for p in chosen:
                results.append(print_one(p, order, settings, default_name))
            return self.send_json(200, {'ok': True, 'results': results})
        except Exception as e:
            return self.send_json(500, {'ok': False, 'error': str(e), 'trace': traceback.format_exc(limit=2)})
    def log_message(self, fmt, *args): print('[%s] %s' % (self.log_date_time_string(), fmt % args))

if __name__ == '__main__':
    print('Top Kabda Print Bridge: http://127.0.0.1:3210')
    print('Do not close this window while automatic printing is required.')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
