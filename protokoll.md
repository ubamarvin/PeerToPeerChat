Protokollspezifikation Server-basierter Peer-to-Peer Group Chat

Diese Datei beschreibt das Protokoll, das von chat_server.py und
chat_client.py tatsaechlich implementiert wird.


1. Allgemeines Nachrichtenformat

1.1 TCP-Framing

Alle TCP-Nachrichten, sowohl zwischen Client und Server als auch zwischen
zwei Peers, bestehen aus:

    4 Byte Laengenfeld + JSON-Payload

Das Laengenfeld ist ein unsigned 32-bit Integer in Network Byte Order
(big endian). Es beschreibt die Laenge des folgenden JSON-Payloads in Bytes.
Der JSON-Payload ist UTF-8 kodiert.

Nachrichten mit einer Laenge kleiner/gleich 0 oder groesser als 1 MiB werden
als ungueltig behandelt.

1.2 UDP-Framing

UDP-Nachrichten zwischen Peers enthalten direkt einen UTF-8 kodierten
JSON-Payload. Es gibt kein Laengenfeld, da UDP Datagrammgrenzen erhaelt.

1.3 JSON-Objekte

User:

{
  "nick": "alice",
  "ip_addr": "127.0.0.1",
  "udp_port": 40001
}

Message:

{
  "type": "MESSAGE_TYPE",
  "user": { ... },
  "userlist": [ ... ],
  "broadcasting_user": { ... },
  "msg": "Text"
}

Nicht jede Nachricht verwendet alle Felder. Unbenutzte Felder koennen fehlen.


2. Client-Server-Protokoll ueber TCP

2.1 Registrierung

Client -> Server:

{
  "type": "REGISTER",
  "user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  }
}

Aus Kompatibilitaetsgruenden akzeptiert der Server auch diese Kurzform:

{
  "type": "REGISTER",
  "nick": "alice",
  "udp": 40001
}

Falls keine IP-Adresse angegeben ist, verwendet der Server die IP-Adresse der
TCP-Verbindung.

Server -> Client bei Erfolg:

{
  "type": "REGISTER_OK",
  "user": {
    "nick": "SERVER",
    "ip_addr": "127.0.0.1",
    "udp_port": 50001
  }
}

Danach sendet der Server die aktuelle Nutzerliste:

{
  "type": "USER_LIST",
  "user": {
    "nick": "SERVER",
    "ip_addr": "127.0.0.1",
    "udp_port": 50001
  },
  "userlist": [
    {
      "nick": "alice",
      "ip_addr": "127.0.0.1",
      "udp_port": 40001
    }
  ]
}

Server -> Client bei Fehler:

{
  "type": "REGISTER_FAIL",
  "user": {
    "nick": "SERVER",
    "ip_addr": "127.0.0.1",
    "udp_port": 50001
  }
}

Gruende fuer REGISTER_FAIL:

- Nickname fehlt oder ist leer.
- UDP-Port fehlt, ist keine Zahl oder liegt nicht im Bereich 1 bis 65535.
- Nickname ist bereits registriert.
- Dieselbe TCP-Verbindung versucht sich mehrfach zu registrieren.

2.2 Nutzer-Updates

Wenn ein Nutzer beitritt, sendet der Server an alle registrierten Clients:

{
  "type": "USER_JOINED",
  "user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  }
}

Wenn ein Nutzer die TCP-Verbindung zum Server beendet oder die Verbindung
abbricht, entfernt der Server den Nutzer und sendet:

{
  "type": "USER_LEFT",
  "user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  }
}

Es gibt keine separate LOGOFF-Nachricht. Abmelden erfolgt durch Schliessen der
TCP-Verbindung zum Server.

2.3 Broadcast

Client -> Server:

{
  "type": "BROADCAST",
  "user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  },
  "msg": "Hallo zusammen"
}

Server -> alle registrierten Clients:

{
  "type": "BROADCAST",
  "user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  },
  "broadcasting_user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  },
  "msg": "Hallo zusammen"
}

Der Server verwendet den Nutzer, der zu der TCP-Verbindung gehoert, als
Absender. Ein gefaelschtes user-Feld in der BROADCAST-Anfrage bestimmt also
nicht den Broadcast-Absender.

Server -> Client bei Fehler:

{
  "type": "MESSAGE_FAIL",
  "user": {
    "nick": "SERVER",
    "ip_addr": "127.0.0.1",
    "udp_port": 50001
  }
}

Gruende fuer MESSAGE_FAIL:

- BROADCAST wird vor erfolgreicher Registrierung gesendet.
- msg fehlt, ist kein String oder ist leer.
- type ist leer, fehlt oder unbekannt.
- MESSAGE wird faelschlicherweise an den Server gesendet.
- JSON ist ungueltig.


3. Peer-Verbindungsaufbau ueber UDP und TCP

Wenn Client A mit Client B chatten will, sendet A zunaechst per UDP eine
Einladung an die in der Nutzerliste gespeicherte IP-Adresse und den UDP-Port
von B.

Client A -> Client B ueber UDP:

{
  "type": "PEER_INVITE",
  "user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  },
  "tcp_ip": "127.0.0.1",
  "tcp_port": 41001
}

Client B -> Client A ueber UDP:

{
  "type": "PEER_INVITE_ACK",
  "user": {
    "nick": "bob",
    "ip_addr": "127.0.0.1",
    "udp_port": 40002
  }
}

Nach dem Empfang einer gueltigen PEER_INVITE baut Client B eine TCP-Verbindung
zu tcp_ip:tcp_port von Client A auf. Diese TCP-Verbindung wird anschliessend
fuer direkte Chatnachrichten verwendet.

Bad Path:

- Ungueltiges JSON per UDP wird ignoriert.
- Unbekannte UDP-Typen werden ignoriert.
- PEER_INVITE ohne Nickname oder ohne gueltigen tcp_port wird ignoriert.
- Wenn der Empfaenger bereits in einer Peer-Verbindung ist, wird die Einladung
  ignoriert.
- Wenn der TCP-Verbindungsaufbau fehlschlaegt, wird lokal eine Fehlermeldung
  ausgegeben.
- UDP-Paketverlust wird in der aktuellen Implementierung nicht durch
  Wiederholungen kompensiert. Der Initiator sendet eine Einladung und wartet
  bis zu 30 Sekunden auf die TCP-Verbindung.


4. Peer-Chat-Protokoll ueber TCP

Peer -> Peer:

{
  "type": "MESSAGE",
  "user": {
    "nick": "alice",
    "ip_addr": "127.0.0.1",
    "udp_port": 40001
  },
  "msg": "Hallo Bob"
}

Die Nachricht wird ueber die bestehende Peer-TCP-Verbindung mit demselben
4-Byte-Laengenfeld wie im Client-Server-Protokoll versendet.

Peer -> Peer bei ungueltiger direkter Nachricht:

{
  "type": "MESSAGE_FAIL"
}

Gruende fuer MESSAGE_FAIL im Peer-Chat:

- type ist unbekannt.
- MESSAGE enthaelt keinen Text.
- MESSAGE enthaelt keinen Absender-Nickname und es gibt keinen bekannten Peer.

Peer -> Peer beim sauberen Beenden:

{
  "type": "DISCONNECT"
}

Nach DISCONNECT oder nach einem Verbindungsfehler wird die Peer-Verbindung
geschlossen.


5. Bekannte Einschraenkungen

- UDP-Einladungen werden nicht erneut gesendet, wenn das Paket verloren geht.
- Es gibt keine explizite Authentifizierung. Nicknames muessen lediglich
  eindeutig sein.
- Der Server speichert Nutzer nur solange ihre TCP-Verbindung zum Server lebt.
- Der Client unterstuetzt immer nur eine aktive Peer-Verbindung gleichzeitig.
