"""Local synthetic fixture only. Never connect this example to business datasets."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        key = Path(os.environ['SAMPLE_KEY_FILE']).read_text().strip()
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + key):
            self.respond(401, {'error': 'unauthorized'})
            return
        url = urlsplit(self.path)
        if url.path == '/health':
            self.respond(200, {'ok': True})
            return
        if url.path == '/records':
            query = parse_qs(url.query)
            try:
                limit = max(1, min(20, int(query.get('limit', ['5'])[0])))
            except ValueError:
                self.respond(400, {'error': 'invalid_limit'})
                return
            keyword = query.get('q', [''])[0]
            items = [{'id': 'demo' + str(i), 'name': name, 'content': content} for i, (name, content) in enumerate([
                ('资料甲', '合成记录：青梧县柳溪镇云杉路卡口周一完成演示设备巡检，不对应真实点位。'),
                ('资料乙', '合成记录：南埠夜市口卡口培训材料已按演示口径整理，仅供对练。'),
                ('资料丙', '合成记录：东津巷口卡口本周演示计划已更新，不含真实案件。'),
                ('资料丁', '合成记录：西津农贸市场卡口演示巡检已登记。'),
                ('资料戊', '合成记录：柳溪镇车站卡口演示值守表已替换。'),
                ('资料己', '合成记录：南埠步行街卡口演示设备在线。'),
            ], 1)]
            self.respond(200, {'items': [item for item in items if keyword in item['name'] or keyword in item['content']][:limit]})
            return
        self.respond(404, {'error': 'not_found'})

    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8090'))), Handler).serve_forever()
