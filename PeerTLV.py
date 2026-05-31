import argparse
import json
import socket
import struct
import threading
import time

from user import PeerInfo


SERVER_HOST = "127.0.0.1"
SERVER_TCP_PORT = 12000
TIMEOUT_SECONDS = 5
MAX_PAYLOAD_SIZE = 1024 * 1024


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


def local_ip_for_remote(remote_ip):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((remote_ip, 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


class MinimalPeer:
    def __init__(
        self,
        nickname,
        ip_address=None,
        udp_port=5002,
        server_host=SERVER_HOST,
        server_port=SERVER_TCP_PORT,
    ):
        self.server_host = server_host
        self.server_port = server_port
        self.nickname = nickname
        self.my_info = PeerInfo(
            nickname,
            ip_address or local_ip_for_remote(server_host),
            udp_port,
            tcp_port=None,
        )
        self.server_tcp_socket = None
        self.udp_socket = None
        self.tcp_listener = None
        self.peer_socket = None
        self.peer_user = None
        self.is_registered = False
        self.running = False
        self.user_list = []
        self.user_list_lock = threading.Lock()
        self.peer_lock = threading.Lock()
        self.server_ready = threading.Event()
        self.user_list_ready = threading.Event()
        self.peer_ready = threading.Event()

    def start(self):
        print(f"[{self.my_info.name}] Starting peer...")
        self.running = True
        if not self._start_peer_sockets():
            self.stop()
            return False
        if not self._connect_to_server():
            self.stop()
            return False

        threading.Thread(target=self._udp_listener, daemon=True).start()
        threading.Thread(target=self._tcp_listener_loop, daemon=True).start()
        threading.Thread(target=self._server_receiver, daemon=True).start()
        self._register_on_chat()

        if not self.server_ready.wait(timeout=TIMEOUT_SECONDS):
            print(f"[{self.nickname}] Registration timed out.")
            self.stop()
            return False

        if self.is_registered:
            print(f"[{self.nickname}] Registration complete.")
        else:
            self.stop()

        return self.is_registered

    def cli_run(self):
        if not self.is_registered:
            print(f"[{self.nickname}] CLI cannot start: peer is not registered.")
            return

        self._cli_loop()

    def _connect_to_server(self):
        try:
            self.server_tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_tcp_socket.settimeout(TIMEOUT_SECONDS)
            self.server_tcp_socket.connect((self.server_host, self.server_port))
            self.server_tcp_socket.settimeout(None)
            return True
        except ConnectionRefusedError:
            print(f"[{self.nickname}] Server is not reachable.")
        except socket.timeout:
            print(f"[{self.nickname}] Connection to server timed out.")
        except OSError as exc:
            print(f"[{self.nickname}] Could not connect to server: {exc}")
        return False

    def _start_peer_sockets(self):
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.bind(("0.0.0.0", self.my_info.udp_port))
            self.udp_socket.settimeout(0.5)
            self.my_info.udp_port = self.udp_socket.getsockname()[1]

            self.tcp_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_listener.bind(("0.0.0.0", 0))
            self.tcp_listener.listen(1)
            self.tcp_listener.settimeout(0.5)
            self.my_info.tcp_port = self.tcp_listener.getsockname()[1]
            return True
        except OSError as exc:
            print(f"[{self.nickname}] Could not start peer sockets: {exc}")
            return False

    def _register_on_chat(self):
        register = {
            "type": "REGISTER",
            "user": self.my_info.to_protocol_user(),
        }
        try:
            send_message(self.server_tcp_socket, register)
            print(f"[{self.my_info.name}] REGISTER sent.")
        except OSError as exc:
            print(f"[{self.my_info.name}] Could not send REGISTER: {exc}")
            self.server_ready.set()

    def _server_receiver(self):
        try:
            while self.running:
                message = recv_message(self.server_tcp_socket)
                self._handle_server_message(message)
        except (ConnectionError, OSError, socket.timeout) as exc:
            if self.running:
                print(f"[{self.nickname}] Server connection closed: {exc}")
        except (json.JSONDecodeError, UnicodeDecodeError, struct.error) as exc:
            print(f"[{self.nickname}] Invalid server message: {exc}")
        finally:
            self.running = False
            self.server_ready.set()
            self.user_list_ready.set()

    def _handle_server_message(self, message):
        msg_type = message.get("type", "")
        if msg_type == "REGISTER_OK":
            self.is_registered = True
            self.server_ready.set()
            print(f"[{self.nickname}] REGISTER_OK received.")
        elif msg_type == "REGISTER_FAIL":
            self.is_registered = False
            self.server_ready.set()
            reason = message.get("msg") or "Registration failed."
            print(f"[{self.nickname}] REGISTER_FAIL: {reason}")
        elif msg_type == "USER_LIST":
            self._replace_user_list(message.get("userlist", []))
            self.user_list_ready.set()
            self.print_user_list()
        elif msg_type == "USER_JOINED":
            self._upsert_user(message.get("user", {}))
            joined = message.get("user", {}).get("nick", "")
            if joined and joined != self.nickname:
                print(f"[Server] User joined: {joined}")
            self.print_user_list()
        elif msg_type == "USER_LEFT":
            left = message.get("user", {}).get("nick", "")
            self._remove_user(left)
            if left:
                print(f"[Server] User left: {left}")
            self.print_user_list()
        elif msg_type == "BROADCAST":
            sender = message.get("broadcasting_user") or message.get("user") or {}
            sender_nick = sender.get("nick", "server")
            print(f"[broadcast] {sender_nick}: {message.get('msg', '')}")
        elif msg_type == "MESSAGE_FAIL":
            reason = message.get("msg") or "Message rejected."
            print(f"[Server] MESSAGE_FAIL: {reason}")
        else:
            print(f"[Server] Ignoring unknown message type: {msg_type}")

    def _replace_user_list(self, users):
        with self.user_list_lock:
            self.user_list = [user for user in users if isinstance(user, dict)]

    def _upsert_user(self, user):
        if not isinstance(user, dict) or not user.get("nick"):
            return
        with self.user_list_lock:
            self.user_list = [existing for existing in self.user_list if existing.get("nick") != user["nick"]]
            self.user_list.append(user)

    def _remove_user(self, nick):
        with self.user_list_lock:
            self.user_list = [user for user in self.user_list if user.get("nick") != nick]

    def print_user_list(self):
        with self.user_list_lock:
            users = list(self.user_list)
        print("\n=== Active users ===")
        others = [user for user in users if user.get("nick") != self.nickname]
        if not others:
            print("No other users active.")
        else:
            for user in others:
                print(f"  - {user.get('nick')} | {user.get('ip_addr')}:{user.get('udp_port')}")
        print("====================\n")

    def _send_broadcast(self, text):
        if not self.is_registered:
            print("Error: peer is not registered.")
            return
        message = {
            "type": "BROADCAST",
            "user": self.my_info.to_protocol_user(),
            "msg": text,
        }
        try:
            send_message(self.server_tcp_socket, message)
        except OSError as exc:
            print(f"[{self.nickname}] Could not send broadcast: {exc}")

    def _udp_listener(self):
        while self.running:
            try:
                payload, address = self.udp_socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                message = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            msg_type = message.get("type", "")
            if msg_type == "PEER_INVITE":
                self._handle_peer_invite(message, address)
            elif msg_type == "PEER_INVITE_ACK":
                sender = message.get("user", {}).get("nick", address[0])
                print(f"[peer] Invite ACK from {sender}")

    def _tcp_listener_loop(self):
        while self.running:
            try:
                conn, _ = self.tcp_listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            conn.settimeout(None)
            with self.peer_lock:
                if self.peer_socket is not None:
                    conn.close()
                    continue
                self.peer_socket = conn
            self.peer_ready.set()
            print("[peer] Direct TCP connection established.")
            threading.Thread(target=self._peer_receiver, args=(conn,), daemon=True).start()

    def _handle_peer_invite(self, message, address):
        sender = message.get("user", {})
        sender_nick = sender.get("nick", "")
        tcp_ip = message.get("tcp_ip") or sender.get("ip_addr") or address[0]
        try:
            tcp_port = int(message.get("tcp_port", 0))
        except (TypeError, ValueError):
            tcp_port = 0

        if not sender_nick or tcp_port <= 0:
            return

        with self.peer_lock:
            if self.peer_socket is not None:
                print(f"[peer] Busy, ignoring invite from {sender_nick}.")
                return
            self.peer_user = sender

        ack = {
            "type": "PEER_INVITE_ACK",
            "user": self.my_info.to_protocol_user(),
        }
        try:
            self.udp_socket.sendto(json.dumps(ack).encode("utf-8"), address)
        except OSError:
            pass

        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.settimeout(TIMEOUT_SECONDS)
            conn.connect((tcp_ip, tcp_port))
            conn.settimeout(None)
            with self.peer_lock:
                self.peer_socket = conn
            self.peer_ready.set()
            print(f"[peer] Connected to {sender_nick}.")
            threading.Thread(target=self._peer_receiver, args=(conn,), daemon=True).start()
        except OSError as exc:
            print(f"[peer] Could not connect to {sender_nick}: {exc}")
            with self.peer_lock:
                self.peer_user = None

    def _connect_to_peer(self, nick):
        target = self._find_user(nick)
        if target is None:
            print(f"[peer] Unknown user: {nick}")
            return
        if target.get("nick") == self.nickname:
            print("[peer] Cannot connect to yourself.")
            return

        with self.peer_lock:
            if self.peer_socket is not None:
                print("[peer] Already connected. Use disconnect first.")
                return
            self.peer_user = target

        invite = {
            "type": "PEER_INVITE",
            "user": self.my_info.to_protocol_user(),
            "tcp_ip": self.my_info.ip_address,
            "tcp_port": self.my_info.tcp_port,
        }
        try:
            self.udp_socket.sendto(
                json.dumps(invite).encode("utf-8"),
                (target["ip_addr"], int(target["udp_port"])),
            )
            print(f"[peer] Invite sent to {target['nick']}. Waiting for TCP connection...")
        except OSError as exc:
            print(f"[peer] Could not send invite: {exc}")
            return

        if not self.peer_ready.wait(timeout=30.0):
            print("[peer] Peer connection did not establish in time.")
            with self.peer_lock:
                self.peer_user = None

    def _find_user(self, nick):
        with self.user_list_lock:
            for user in self.user_list:
                if user.get("nick") == nick:
                    return user
        return None

    def _send_peer_message(self, text):
        with self.peer_lock:
            conn = self.peer_socket
        if conn is None:
            print("[peer] No active peer connection.")
            return

        message = {
            "type": "MESSAGE",
            "user": self.my_info.to_protocol_user(),
            "msg": text,
        }
        try:
            send_message(conn, message)
        except OSError as exc:
            print(f"[peer] Could not send message: {exc}")
            self._close_peer(announce=False)

    def _peer_receiver(self, conn):
        try:
            while self.running:
                message = recv_message(conn)
                msg_type = message.get("type", "")
                if msg_type == "MESSAGE":
                    sender = message.get("user", {}).get("nick", "peer")
                    text = message.get("msg", "")
                    if not text:
                        send_message(conn, {"type": "MESSAGE_FAIL"})
                        break
                    print(f"[direct] {sender}: {text}")
                elif msg_type == "MESSAGE_FAIL":
                    print("[peer] MESSAGE_FAIL received.")
                elif msg_type == "DISCONNECT":
                    print("[peer] Peer disconnected.")
                    break
                else:
                    send_message(conn, {"type": "MESSAGE_FAIL"})
                    break
        except ConnectionError:
            if self.running:
                print("[peer] Direct peer connection closed.")
        except (OSError, socket.timeout):
            pass
        finally:
            self._close_peer(announce=False)

    def _close_peer(self, announce=True):
        with self.peer_lock:
            conn = self.peer_socket
            self.peer_socket = None
            self.peer_user = None
            self.peer_ready.clear()
        closed = conn is not None
        if conn is not None:
            try:
                if announce:
                    send_message(conn, {"type": "DISCONNECT"})
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        return closed

    def stop(self):
        self.running = False
        self.is_registered = False
        if self.server_tcp_socket:
            try:
                self.server_tcp_socket.close()
            except OSError:
                pass
        self._close_peer(announce=False)
        for sock in (self.udp_socket, self.tcp_listener):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        print(f"[{self.my_info.name}] Peer stopped.")

    def _cli_loop(self):
        while self.running and self.is_registered:
            try:
                command = input(
                    f"[{self.nickname}] Command (list, connect <nick>, msg <text>, "
                    "broadcast <text>, disconnect, quit): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not command:
                continue

            command_name, _, argument = command.partition(" ")
            command_name = command_name.lower()

            if command_name in {"quit", "deregister", "exit", "q"}:
                break
            if command_name in {"list", "l"}:
                self.print_user_list()
            elif command_name == "connect":
                if argument.strip():
                    self._connect_to_peer(argument.strip())
                else:
                    print("Usage: connect <nick>")
            elif command_name == "msg":
                if argument.strip():
                    self._send_peer_message(argument.strip())
                else:
                    print("Usage: msg <text>")
            elif command_name == "broadcast":
                if argument.strip():
                    self._send_broadcast(argument.strip())
                else:
                    print("Usage: broadcast <text>")
            elif command_name == "disconnect":
                if self._close_peer():
                    print("[peer] Direct peer connection closed.")
                else:
                    print("[peer] No active peer connection.")
            else:
                print(f"Unknown command: {command_name}")

        self.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-ip", default=SERVER_HOST)
    parser.add_argument("--server-port", type=int, default=SERVER_TCP_PORT)
    parser.add_argument("--nick", default="")
    parser.add_argument("--ip", default="")
    parser.add_argument("--udp-port", type=int, default=5002)
    args = parser.parse_args()

    nick = args.nick or input("Nickname: ").strip()
    if not nick:
        raise SystemExit("Nickname is required.")

    peer = MinimalPeer(
        nickname=nick,
        ip_address=args.ip or None,
        udp_port=args.udp_port,
        server_host=args.server_ip,
        server_port=args.server_port,
    )
    if peer.start():
        time.sleep(0.1)
        peer.cli_run()
