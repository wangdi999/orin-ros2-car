import socket
import threading


HOST = "0.0.0.0"
PORT = 9090


def handle_client(conn, addr):
    print(f"[mock-tcp] client connected: {addr}")
    try:
        with conn.makefile("r", encoding="utf-8", errors="replace") as reader:
            for line in reader:
                message = line.strip()
                if message:
                    print(f"[mock-tcp] received: {message}")
    except Exception as exc:
        print(f"[mock-tcp] error: {exc}")
    finally:
        conn.close()
        print(f"[mock-tcp] client disconnected: {addr}")


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        print(f"[mock-tcp] mock control server listening on {HOST}:{PORT}")
        print("[mock-tcp] emulator app host: 10.0.2.2, port: 9090, mode: 模拟测试：开")

        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
