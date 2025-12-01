from user import User
import socket
import time

##                  name, udp, ip
testUser_1 = User("Luis", 5000, '127.0.0.1')

def registerOnChat(user):
    print("register")

def unsubscribe(user):
    print("logout")

def sendOpenTcpPortviaUdp(tcpPort):
    print("")

def receiveOpenTcpPortViaUdp():
    print("")

def connectToPeer():
    print("")


if __name__ == "__main__":
    print()
###tcpSocket zum Server als client

###Udp Socket zum Peer zur chat Anfrage

###tcpSocket zum Peer zum chat als Server/Listener
    ###Mit jedem chat Anfrage muss ein neuer
    ###Socket erstellt werden

###tcpSocker zum Peer zum Nachrichtenaustausch als Client
    ###Hier muss ich auch für jeden neuen chat einen socket aufbauen?