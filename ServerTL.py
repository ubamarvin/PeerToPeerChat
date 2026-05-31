import argparse
import json
import socket
import struct
import threading


SERVER_TCP_PORT = 12000
MAX_PAYLOAD_SIZE = 1024 * 1024
BUFFER_TIMEOUT = 600


def make_user(nick="", ip_addr="", udp_port=0):
    return {
        "nick": nick or "",
        "ip_addr": ip_addr or "",
        "udp_port": int(udp_port or 0),
    }


def message_to_bytes(message):
    payload = json.dumps(message).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


def recv_exact(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data += chunk
    return data


def recv_message(conn):
    header = recv_exact(conn, 4)
    (payload_len,) = struct.unpack("!I", header)
    if payload_len <= 0 or payload_len > MAX_PAYLOAD_SIZE:
        raise ConnectionError("invalid payload length")
    payload = recv_exact(conn, payload_len)
    return json.loads(payload.decode("utf-8"))


def send_message(conn, message):
    conn.sendall(message_to_bytes(message))


def user_from_message(message, conn=None):
    raw_user = message.get("user")
    if isinstance(raw_user, dict):
        nick = raw_user.get("nick", "")
        ip_addr = raw_user.get("ip_addr", "")
        udp_port = raw_user.get("udp_port", raw_user.get("udp", 0))
    else:
        nick = message.get("nick", "")
        ip_addr = message.get("ip_addr", "")
        udp_port = message.get("udp", message.get("udp_port", 0))

    if not ip_addr and conn is not None:
        ip_addr = conn.getpeername()[0]

    try:
        udp_port = int(udp_port)
    except (TypeError, ValueError):
        udp_port = 0

    return make_user(nick, ip_addr, udp_port)


class ChatServer:
    def __init__(self, tcp_port=SERVER_TCP_PORT, bind_ip="0.0.0.0"):
        self.tcp_port = tcp_port
        self.bind_ip = bind_ip
        self.server_user = make_user("SERVER", bind_ip, tcp_port)
        self.peers = {}
        self.lock = threading.RLock()
        self.running = False
        self.tcp_sock = None

    def start(self):
        try:
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_sock.bind((self.bind_ip, self.tcp_port))
            self.tcp_sock.listen(5)
            self.tcp_sock.settimeout(1.0)
            self.server_user["ip_addr"], self.server_user["udp_port"] = self.tcp_sock.getsockname()
            self.running = True
            threading.Thread(target=self._accept_connections_loop, daemon=True).start()
            print(f"[Server] Listening on {self.tcp_sock.getsockname()}")
        except Exception as exc:
            print(f"[Server] Start failed: {exc}")
            self._close_all()

    def _accept_connections_loop(self):
        while self.running:
            try:
                conn, addr = self.tcp_sock.accept()
                print(f"[Server] Connection from {addr}")
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as exc:
                if self.running:
                    print(f"[Server] Accept error: {exc}")
                break
        print("[Server] Accept loop stopped.")

    def _handle_client(self, conn):
        conn.settimeout(BUFFER_TIMEOUT)
        try:
            while self.running:
                message = recv_message(conn)
                self._handle_message(conn, message)
        except (ConnectionError, socket.timeout, OSError):
            pass
        except (json.JSONDecodeError, UnicodeDecodeError, struct.error):
            self._send_message_fail(conn)
        except Exception as exc:
            print(f"[Server] Client handler error: {exc}")
        finally:
            self._remove_peer(conn)
            try:
                conn.close()
            except OSError:
                pass

    def _handle_message(self, conn, message):
        msg_type = message.get("type", "")
        if msg_type == "REGISTER":
            self._handle_register(conn, message)
        elif msg_type == "BROADCAST":
            self._handle_broadcast(conn, message)
        else:
            self._send_message_fail(conn)

    def _handle_register(self, conn, message):
        user = user_from_message(message, conn)
        user["nick"] = user["nick"].strip()

        if not user["nick"]:
            self._refuse_register(conn, user, "Nickname is required.")
            return

        if not self._valid_udp_port(user["udp_port"]):
            self._refuse_register(conn, user, "UDP port must be between 1 and 65535.")
            return

        with self.lock:
            already_registered = any(peer["conn"] == conn for peer in self.peers.values())
            nick_taken = user["nick"] in self.peers
            if already_registered:
                self._refuse_register(conn, user, "This TCP connection is already registered.")
                return
            if nick_taken:
                self._refuse_register(conn, user, f"User {user['nick']} already exists.")
                return
            self.peers[user["nick"]] = {"user": user, "conn": conn}

        self._broadcast({"type": "USER_JOINED", "user": user})
        send_message(conn, {"type": "REGISTER_OK", "user": self.server_user})
        send_message(conn, {"type": "USER_LIST", "user": self.server_user, "userlist": self._user_list()})
        print(f"[Server] Registered {user['nick']} ({user['ip_addr']}:{user['udp_port']})")

    def _handle_broadcast(self, conn, message):
        sender = self._user_for_conn(conn)
        text = message.get("msg", "")
        if sender is None or not isinstance(text, str) or not text.strip():
            self._send_message_fail(conn)
            return

        broadcast = {
            "type": "BROADCAST",
            "user": sender,
            "broadcasting_user": sender,
            "msg": text,
        }
        self._broadcast(broadcast)

    def _remove_peer(self, conn):
        removed_user = None
        with self.lock:
            for nick, peer in list(self.peers.items()):
                if peer["conn"] == conn:
                    removed_user = peer["user"]
                    del self.peers[nick]
                    break
        if removed_user is not None:
            print(f"[Server] Removed {removed_user['nick']}")
            self._broadcast({"type": "USER_LEFT", "user": removed_user})

    def _user_for_conn(self, conn):
        with self.lock:
            for peer in self.peers.values():
                if peer["conn"] == conn:
                    return peer["user"]
        return None

    def _user_list(self):
        with self.lock:
            return [peer["user"] for peer in self.peers.values()]

    def _broadcast(self, message):
        with self.lock:
            recipients = [peer["conn"] for peer in self.peers.values()]
        for conn in recipients:
            try:
                send_message(conn, message)
            except OSError:
                self._remove_peer(conn)

    def _refuse_register(self, conn, user, reason):
        try:
            remote = conn.getpeername()
        except OSError:
            remote = ("unknown", 0)
        nick = user.get("nick") or "<missing>"
        udp_port = user.get("udp_port")
        print(
            f"[Server] Refused registration from {remote[0]}:{remote[1]} "
            f"nick={nick} udp_port={udp_port}: {reason}"
        )
        self._send_register_fail(conn, reason)

    def _send_register_fail(self, conn, reason="Registration failed."):
        try:
            send_message(conn, {"type": "REGISTER_FAIL", "user": self.server_user, "msg": reason})
        except OSError:
            pass

    def _send_message_fail(self, conn, reason="Message rejected."):
        try:
            send_message(conn, {"type": "MESSAGE_FAIL", "user": self.server_user, "msg": reason})
        except OSError:
            pass

    @staticmethod
    def _valid_udp_port(port):
        return isinstance(port, int) and 1 <= port <= 65535

    def _close_all(self):
        self.running = False
        if self.tcp_sock is not None:
            try:
                self.tcp_sock.close()
            except OSError:
                pass
        with self.lock:
            conns = [peer["conn"] for peer in self.peers.values()]
            self.peers.clear()
        for conn in conns:
            try:
                conn.close()
            except OSError:
                pass
        print("[Server] Stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=SERVER_TCP_PORT)
    args = parser.parse_args()

    server = ChatServer(args.port, args.ip)
    server.start()
    try:
        while server.running:
            command = input("Server running. Type 'quit' to stop: ").strip().lower()
            if command == "quit":
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        server._close_all()
