class PeerInfo:
    def __init__(self, name, ip_address, udp_port, tcp_port=None):
        self.name = name
        self.ip_address = ip_address
        self.udp_port = int(udp_port)
        self.tcp_port = int(tcp_port) if tcp_port is not None else None

    def __str__(self):
        tcp = self.tcp_port if self.tcp_port is not None else "N/A"
        return f"PeerInfo(name={self.name}, ip={self.ip_address}, udp={self.udp_port}, tcp={tcp})"

    def __repr__(self):
        return self.__str__()

    def to_protocol_user(self):
        return {
            "nick": self.name,
            "ip_addr": self.ip_address,
            "udp_port": self.udp_port,
        }

    def to_dict(self):
        return self.to_protocol_user()

    @classmethod
    def from_protocol_user(cls, data):
        return cls(
            name=data["nick"],
            ip_address=data["ip_addr"],
            udp_port=data["udp_port"],
        )

    @classmethod
    def from_dict(cls, data):
        if "nick" in data:
            return cls.from_protocol_user(data)
        return cls(
            name=data["nickname"],
            ip_address=data["ip"],
            udp_port=data["udp_port"],
        )
