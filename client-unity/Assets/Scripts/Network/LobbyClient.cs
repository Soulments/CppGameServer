using System;
using CppGameServer.Protocol;
using Google.Protobuf;

namespace CppGameServer.Network
{
    /// <summary>
    /// 로그인과 방 입장 프로토콜(proto/game.proto)을 다루는 클라이언트. GameClient 위에서 동작한다.
    /// 이벤트는 GameClient.Tick() 을 부르는 스레드(Unity 메인 스레드)에서 발생한다.
    ///
    /// 서버가 보낸 payload 를 해석하지 못하면(프로토콜 위반) 연결을 끊는다. 서버도 같은 정책이다.
    /// </summary>
    public sealed class LobbyClient
    {
        private readonly GameClient _client;

        /// <summary>로그인 응답. 성공이면 result 가 ResultOk 이고 player 가 채워진다.</summary>
        public event Action<ResultCode, PlayerInfo> LoginCompleted;

        /// <summary>방 입장 응답. 성공이면 입장한 본인을 포함한 방 전체 인원이 들어 있다.</summary>
        public event Action<JoinRoomResponse> RoomJoinCompleted;

        /// <summary>같은 방에 다른 플레이어가 들어왔다.</summary>
        public event Action<PlayerInfo> OtherPlayerJoined;

        /// <summary>같은 방의 다른 플레이어가 나갔다 (player_id).</summary>
        public event Action<ulong> OtherPlayerLeft;

        /// <summary>방에 있는 동안 서버 틱(20Hz)마다 오는 월드 스냅샷. 보간과 예측 보정은 이 이벤트를 받아서 처리한다.</summary>
        public event Action<WorldSnapshot> SnapshotReceived;

        public LobbyClient(GameClient client)
        {
            if (client == null) throw new ArgumentNullException("client");
            _client = client;
            _client.PacketReceived += OnPacket;
        }

        public bool Login(string nickname)
        {
            var request = new LoginRequest { Nickname = nickname ?? string.Empty };
            return _client.Send(PacketProtocol.LoginRequest, request.ToByteArray());
        }

        public bool JoinRoom(uint roomId)
        {
            var request = new JoinRoomRequest { RoomId = roomId };
            return _client.Send(PacketProtocol.JoinRoomRequest, request.ToByteArray());
        }

        /// <summary>
        /// 이동 입력을 보낸다. seq 는 1부터 늘려 가는 번호이고, 서버는 이전 값보다 작거나 같은 번호를 버린다.
        /// 방향은 서버가 크기를 1 이하로 제한한다. 위치가 아니라 입력을 보내는 것이 서버 권위 구조의 핵심이다.
        /// </summary>
        public bool SendMoveInput(uint seq, float dirX, float dirZ)
        {
            var input = new MoveInput { Seq = seq, DirX = dirX, DirZ = dirZ };
            return _client.Send(PacketProtocol.MoveInput, input.ToByteArray());
        }

        private void OnPacket(ushort type, byte[] payload)
        {
            try
            {
                switch (type)
                {
                    case PacketProtocol.LoginResponse:
                    {
                        var response = LoginResponse.Parser.ParseFrom(payload);
                        var handler = LoginCompleted;
                        if (handler != null) handler(response.Result, response.Player);
                        break;
                    }
                    case PacketProtocol.JoinRoomResponse:
                    {
                        var response = JoinRoomResponse.Parser.ParseFrom(payload);
                        var handler = RoomJoinCompleted;
                        if (handler != null) handler(response);
                        break;
                    }
                    case PacketProtocol.PlayerJoined:
                    {
                        var message = PlayerJoined.Parser.ParseFrom(payload);
                        var handler = OtherPlayerJoined;
                        if (handler != null) handler(message.Player);
                        break;
                    }
                    case PacketProtocol.PlayerLeft:
                    {
                        var message = PlayerLeft.Parser.ParseFrom(payload);
                        var handler = OtherPlayerLeft;
                        if (handler != null) handler(message.PlayerId);
                        break;
                    }
                    case PacketProtocol.WorldSnapshot:
                    {
                        var snapshot = WorldSnapshot.Parser.ParseFrom(payload);
                        var handler = SnapshotReceived;
                        if (handler != null) handler(snapshot);
                        break;
                    }
                    case PacketProtocol.Pong:
                        break;  // GameClient 가 RTT 를 처리한다
                    default:
                        _client.Disconnect();  // 서버가 보낼 수 없는 타입: 프로토콜 위반
                        break;
                }
            }
            catch (InvalidProtocolBufferException)
            {
                _client.Disconnect();
            }
        }
    }
}
