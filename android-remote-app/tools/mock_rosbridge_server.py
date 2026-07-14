import base64
import hashlib
import socket
import struct
import threading


HOST = "0.0.0.0"
PORT = 9090
MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def recv_until(sock, marker):
    data = b""
    while marker not in data:
        chunk = sock.recv(1024)
        if not chunk:
            break
        data += chunk
    return data


def read_frame(sock):
    header = sock.recv(2)
    if len(header) < 2:
        return None

    first, second = header
    opcode = first & 0x0F
    masked = (second & 0x80) != 0
    length = second & 0x7F

    if length == 126:
        length = struct.unpack(">H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", sock.recv(8))[0]

    mask = sock.recv(4) if masked else b""
    payload = bytearray()
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            break
        payload.extend(chunk)

    if masked:
        payload = bytearray(byte ^ mask[i % 4] for i, byte in enumerate(payload))

    if opcode == 8:
        return None
    if opcode != 1:
        return ""
    return payload.decode("utf-8", errors="replace")


def send_text(sock, text):
    payload = text.encode("utf-8")
    sock.sendall(bytes([0x81]))
    if len(payload) <= 125:
        sock.sendall(bytes([len(payload)]))
    elif len(payload) <= 65535:
        sock.sendall(bytes([126]) + struct.pack(">H", len(payload)))
    else:
        sock.sendall(bytes([127]) + struct.pack(">Q", len(payload)))
    sock.sendall(payload)


def handle_client(conn, addr):
    print(f"[mock] client connected: {addr}")
    try:
        request = recv_until(conn, b"\r\n\r\n").decode("utf-8", errors="replace")
        key = ""
        for line in request.splitlines():
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
                break

        if not key:
            print("[mock] missing websocket key")
            return

        accept = base64.b64encode(hashlib.sha1((key + MAGIC).encode("ascii")).digest()).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        conn.sendall(response.encode("ascii"))
        print("[mock] websocket handshake accepted")

        while True:
            message = read_frame(conn)
            if message is None:
                break
            if message:
                print(f"[mock] received: {message}")
    except Exception as exc:
        print(f"[mock] error: {exc}")
    finally:
        conn.close()
        print(f"[mock] client disconnected: {addr}")


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        print(f"[mock] rosbridge mock server listening on {HOST}:{PORT}")
        print("[mock] set phone app port to 9090 and host to this computer's IPv4 address")

        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
