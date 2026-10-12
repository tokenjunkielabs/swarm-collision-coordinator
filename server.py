import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from coordinator import Coordinator

def serve(path, host='127.0.0.1', port=8891, runtime=None):
    coordinator = Coordinator(path)
    equipment = None
    if runtime:
        import sys
        sys.path.insert(0, runtime)
        from integrations.shared_equipment.services import ServiceEquipment
        from equipment_adapter import CoordinatedCatalog
        equipment = CoordinatedCatalog(ServiceEquipment(), coordinator)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def respond(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.path == '/tools' and equipment:
                self.respond(200, {'tools': list(equipment.tools())}); return
            self.respond(200, {'ok': True, 'service': 'collision-coordination', 'equipment': bool(equipment)} if self.path == '/health' else coordinator.snapshot())
        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', 0))
                if size > 65536: raise ValueError('request too large')
                request = json.loads(self.rfile.read(size))
                if self.path == '/tool-call' and equipment:
                    self.respond(200, equipment.call(request['name'], request.get('arguments', {}))); return
                method = {'/take': coordinator.take, '/progress': coordinator.progress, '/reserve': coordinator.reserve}.get(self.path)
                if method is None:
                    self.respond(404, {'error': 'unknown endpoint'}); return
                self.respond(200, method(request))
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {'error': str(exc)})
    ThreadingHTTPServer((host, port), Handler).serve_forever()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8891)
    parser.add_argument('--commons-runtime')
    args = parser.parse_args()
    serve(args.database, args.host, args.port, args.commons_runtime)
