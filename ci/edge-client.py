import http.client
import json
import contextlib
import os
import socket
import ssl
import time

context = ssl.create_default_context(cafile=os.environ['TEST_CERT'])


def connection():
    client = http.client.HTTPSConnection('test.example.com', context=context, timeout=5)
    client._create_connection = lambda *args, **kwargs: socket.create_connection(('127.0.0.1', 443), timeout=5)
    return client


with contextlib.closing(connection()) as client:
    client.request('GET', '/docs/deep/link', headers={'X-Forwarded-For': '198.51.100.99'})
    response = client.getresponse()
    assert response.status == 200
    assert response.read() == b'/docs/deep/link|127.0.0.1'
    assert response.getheader('Strict-Transport-Security')
    assert response.getheader('X-Content-Type-Options') == 'nosniff'

with contextlib.closing(connection()) as client:
    client.request('GET', '/headers', headers={
        'X-Forwarded-For': '198.51.100.99', 'X-Forwarded-Proto': 'http',
        'X-Forwarded-Host': 'attacker.example.com', 'X-Forwarded-Port': '8080',
        'X-Real-IP': '198.51.100.99', 'Forwarded': 'for=198.51.100.99;proto=http;host=attacker.example.com'})
    headers = json.loads(client.getresponse().read())
    assert headers == {'X-Forwarded-For': '127.0.0.1', 'X-Forwarded-Proto': 'https',
                       'X-Forwarded-Host': 'test.example.com', 'X-Forwarded-Port': '443',
                       'X-Real-IP': '127.0.0.1', 'Forwarded': None}

with contextlib.closing(connection()) as client:
    started = time.monotonic()
    client.request('GET', '/sse')
    response = client.getresponse()
    assert response.readline() == b'data: first\n'
    assert time.monotonic() - started < 1, 'First SSE event was buffered'
    assert b'data: second' in response.read()

with context.wrap_socket(socket.create_connection(('127.0.0.1', 443)), server_hostname='test.example.com') as stream:
    stream.sendall(b'GET /ws HTTP/1.1\r\nHost: test.example.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n')
    response = b''
    while b'\r\n\r\n' not in response:
        response += stream.recv(4096)
    assert b'101 Switching Protocols' in response
    assert b's3pPLMBiTxaQ9kYGzzhZRbK+xOo=' in response
print('PASS docs deep links, forwarding headers, SSE timing and WebSocket handshake')
