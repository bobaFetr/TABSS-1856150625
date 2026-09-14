"""Isolated end-to-end HTTP/CLI checks using a local Binance fixture server."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
results = []


def check(name, condition, detail=''):
    results.append({'name': name, 'passed': bool(condition), 'detail': detail})
    print(('PASS ' if condition else 'FAIL ') + name, flush=True)


def request(base, path, payload=None, method=None, token='system-test-token', raw=None):
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method,
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read().decode()
        try:
            body = json.loads(body)
        except ValueError:
            pass
        return response.status, body


class Market(BaseHTTPRequestHandler):
    counter = 0
    def log_message(self, *args):
        pass
    def do_GET(self):
        if self.path.startswith('/api/v3/klines'):
            payload = [[i, 100+i/10, 102+i/10, 99+i/10, 101+i/10, 1000] for i in range(100)]
        else:
            prices = [150, 145, 155, 140, 160]
            payload = {'price': str(prices[Market.counter % len(prices)])}
            Market.counter += 1
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    with tempfile.TemporaryDirectory(prefix='tabss-system-') as directory:
        env = os.environ.copy()
        env.update(AGENT_DATA_DIR=directory, STATE_FILE=str(Path(directory)/'state.json'),
            OPENAI_API_KEY='', AUTO_SIM_ENABLED='false', AGENT_API_TOKEN='system-test-token',
            AGENT_API_HOST='127.0.0.1', AGENT_API_PORT='8876', BINANCE_RETRY_COUNT='1')
        market = ThreadingHTTPServer(('127.0.0.1', 0), Market)
        threading.Thread(target=market.serve_forever, daemon=True).start()
        env['BINANCE_BASE_URL'] = f'http://127.0.0.1:{market.server_port}'
        backend_log = open(ROOT/'system_backend.log', 'w', encoding='utf-8')
        frontend_log = open(ROOT/'system_frontend.log', 'w', encoding='utf-8')
        backend = subprocess.Popen([sys.executable, 'api_server.py'], cwd=ROOT, env=env,
            stdout=backend_log, stderr=subprocess.STDOUT)
        frontend = None
        base = 'http://127.0.0.1:8876'
        try:
            for _ in range(50):
                try:
                    if request(base, '/health')[0] == 200:
                        break
                except OSError:
                    time.sleep(.1)
            for path in ['/health', '/', '/dashboard', '/state', '/auto/status', '/ap2']:
                status, body = request(base, path)
                check('GET ' + path, status == 200)
            check('unknown route', request(base, '/missing')[0] == 404)
            check('mutating GET rejected', request(base, '/auto/start')[0] == 405)
            check('invalid token rejected', request(base, '/auto/start', {}, token='wrong')[0] == 401)
            check('malformed JSON rejected', request(base, '/auto/start', raw=b'{')[0] == 400)
            check('non-object JSON rejected', request(base, '/auto/start', raw=b'[]')[0] == 400)
            status, body = request(base, '/signal', {})
            check('real HTTP market adapter and fallback signal', status == 200 and body['signal']['signal'] in ['BUY','SELL','HOLD'])
            check('signal persists state', request(base, '/state')[1] != {})
            status, body = request(base, '/auto/configure?startingCash=100&pollSeconds=1&buyCooldownSeconds=0&dropToBuyUsd=1&riseToSellUsd=1', {})
            check('configure stopped runner', status == 200 and not body['auto']['running'])
            check('start runner', request(base, '/auto/start', {})[0] == 200)
            deadline = time.monotonic() + 30
            while True:
                status, body = request(base, '/auto/status')
                if body['auto']['simulation'].get('tradeCount', 0) >= 2 or time.monotonic() >= deadline:
                    break
                time.sleep(.5)
            check('runner produces ticks without errors', bool(body['auto']['lastTickUtc']) and not body['auto']['lastError'], str(body['auto'].get('lastError')))
            check('runner executes trades with real mandate validation', body['auto']['simulation'].get('tradeCount', 0) >= 2, str(body['auto']['simulation']))
            status, body = request(base, '/auto/configure?startingCash=200', {})
            check('configure running runner restarts', status == 200 and body['auto']['running'] and body['auto']['rules']['startingCash'] == 200)
            check('stop runner', not request(base, '/auto/stop', {})[1]['auto']['running'])
            checkout = {'maximumSpendingAmount': 100, 'items': [{'name':'Book','category':'books','quantity':2,'unitPrice':10}]}
            status, body = request(base, '/ap2/checkout/run', checkout)
            check('valid signed checkout', status == 200 and body['checkout']['valid'])
            for name, changes, expected in [
                ('over budget', {'maximumSpendingAmount': 1}, False),
                ('disallowed category', {'allowedCategories':['software']}, False),
                ('missing approval', {'humanApprovalRequired':True}, False),
                ('approved cart', {'humanApprovalRequired':True,'approveCart':True,'humanPresent':True}, True)]:
                status, body = request(base, '/ap2/checkout/run', {**checkout, **changes})
                check('checkout ' + name, status == 200 and body['checkout']['valid'] is expected)
            check('checkout demo', request(base, '/ap2/checkout/demo', {})[0] == 200)
            statuses = list(concurrent.futures.ThreadPoolExecutor(8).map(lambda _: request(base, '/auto/status')[0], range(40)))
            check('40 concurrent status requests', all(s == 200 for s in statuses))
            for args in [['btc_agent.py','--once'], ['ap2_sim.py','--shopping-demo']]:
                process = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
                check('CLI ' + ' '.join(args), process.returncode == 0, process.stderr[-500:])
            data = Path(directory)/'candles.json'
            data.write_text(json.dumps([[i, 100, 102, 99, 101, 1000] for i in range(100)]))
            process = subprocess.run([sys.executable, 'backtest.py', str(data)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            check('backtest CLI', process.returncode == 0 and json.loads(process.stdout)['candles'] == 40)
            env['PY_AGENT_API_URL'] = base
            frontend = subprocess.Popen(['node', 'node_modules/next/dist/bin/next', 'start', '-p', '3301', '-H', '127.0.0.1'], cwd=ROOT/'web', env=env, stdout=frontend_log, stderr=subprocess.STDOUT)
            front = 'http://127.0.0.1:3301'
            for _ in range(100):
                try:
                    if request(front, '/')[0] == 200:
                        break
                except OSError:
                    time.sleep(.1)
            check('production dashboard HTML', request(front, '/')[0] == 200)
            for action in ['health', 'state', 'auto', 'ap2']:
                check('frontend proxy ' + action, request(front, '/api/agent?action=' + action)[0] == 200)
            check('frontend proxy signal', request(front, '/api/agent?action=signal', {})[0] == 200)
            check('frontend proxy checkout', request(front, '/api/agent?action=checkout-run', checkout)[1]['checkout']['valid'])
            check('frontend forwards validation errors', request(front, '/api/agent?action=configure-auto&startingCash=NaN', {})[0] == 400)
        finally:
            if frontend:
                frontend.terminate()
                frontend.wait(timeout=10)
            backend.terminate()
            backend.wait(timeout=10)
            market.shutdown()
            market.server_close()
            backend_log.close()
            frontend_log.close()
            (ROOT/'system_test_results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
