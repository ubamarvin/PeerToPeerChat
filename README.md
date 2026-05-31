# PeerToPeerChat

Server-based peer-to-peer group chat for the Rechnernetze lab.

The server manages registered users and broadcasts user-list updates. Peers
register at the server over TCP, can send server broadcasts, and can open a
direct peer-to-peer TCP chat session using a UDP invite.

## Requirements

- Python 3.10 or newer
- No external Python packages are required

## Start The Server

Run this in the `PeerToPeerChat` folder:

```bash
python3 ServerTL.py
```

By default the server listens on TCP port `12000` on all interfaces.

You can also choose the bind IP and port:

```bash
python3 ServerTL.py --ip 127.0.0.1 --port 12000
```

Stop the server by typing:

```text
quit
```

## Start A Peer

Start a peer in another terminal:

```bash
python3 PeerTLV.py --nick Alice --server-ip 127.0.0.1 --server-port 12000 --udp-port 5002
```

Start a second peer in another terminal:

```bash
python3 PeerTLV.py --nick Bob --server-ip 127.0.0.1 --server-port 12000 --udp-port 5003
```

For use on different machines, replace `127.0.0.1` with the server machine's
reachable IP address. Use a different UDP port for each peer on the same
machine.

## Peer Commands

Once a peer is running, use these commands in the peer terminal:

```text
list
```

Shows all other users currently known from the server's pushed user list.

```text
broadcast <text>
```

Sends a message to the server. The server forwards it to all registered peers.

Example:

```text
broadcast hello everyone
```

```text
connect <nick>
```

Starts a direct peer-to-peer chat session with another registered user. The
initiating peer sends a UDP invite containing its TCP listener address. The
target peer connects back over TCP.

Example:

```text
connect Bob
```

```text
msg <text>
```

Sends a direct TCP message to the connected peer.

Example:

```text
msg hi Bob
```

```text
disconnect
```

Closes the active direct peer-to-peer chat connection. The peer stays
registered at the server and still receives user-list updates and broadcasts.
Use this when you want to end the current private chat but keep the program
running.

```text
quit
```

Stops the peer and closes its server connection.

## Typical Local Test

Use three terminals:

Terminal 1:

```bash
python3 ServerTL.py --ip 127.0.0.1 --port 12000
```

Terminal 2:

```bash
python3 PeerTLV.py --nick Alice --server-ip 127.0.0.1 --server-port 12000 --udp-port 5002
```

Terminal 3:

```bash
python3 PeerTLV.py --nick Bob --server-ip 127.0.0.1 --server-port 12000 --udp-port 5003
```

In Alice's terminal:

```text
list
connect Bob
msg hello Bob
broadcast hello from Alice
disconnect
quit
```

In Bob's terminal, you should see the direct message and the broadcast.

## Protocol Summary

TCP messages use:

```text
4-byte unsigned big-endian JSON length
UTF-8 JSON payload
```

Server message types:

```text
REGISTER
REGISTER_OK
REGISTER_FAIL
USER_LIST
USER_JOINED
USER_LEFT
BROADCAST
MESSAGE_FAIL
```

Peer-to-peer message types:

```text
PEER_INVITE
PEER_INVITE_ACK
MESSAGE
MESSAGE_FAIL
DISCONNECT
```
