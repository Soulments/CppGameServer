using CppGameServer.Protocol;
using UnityEngine;

namespace CppGameServer.Network
{
    /// <summary>
    /// 씬의 빈 GameObject 에 붙여서 쓴다. 시작할 때 서버에 접속하고, 로그인한 뒤 방에 입장한다.
    /// 클라이언트 2개 테스트: 에디터 + 빌드를 같이 실행하거나 빌드를 2개 실행한다 (닉네임은 자동으로 다르게 만든다).
    /// </summary>
    public class GameNetworkManager : MonoBehaviour
    {
        [SerializeField] private string host = "127.0.0.1";
        [SerializeField] private int port = 7777;
        [SerializeField] private float pingIntervalSeconds = 3f;
        [SerializeField] private string nicknamePrefix = "Player";
        [SerializeField] private uint roomId = 1;

        private GameClient _client;
        private LobbyClient _lobby;
        private string _nickname;
        private string _status = "connecting...";
        private string _roomInfo = "";

        private void Awake()
        {
            // 포커스를 잃어도(다른 클라이언트 창을 눌러도) 하트비트가 끊기지 않게 한다.
            Application.runInBackground = true;
        }

        private void Start()
        {
            // 에디터와 빌드가 같은 닉네임으로 충돌하지 않게 무작위 숫자를 붙인다. (서버는 닉네임 중복을 거부한다)
            _nickname = nicknamePrefix + Random.Range(1000, 10000);

            _client = new GameClient();
            _client.PingIntervalSeconds = pingIntervalSeconds;
            _lobby = new LobbyClient(_client);

            _client.Connected += () =>
            {
                _status = "connected, logging in as " + _nickname;
                Debug.Log("[net] connected to " + host + ":" + port);
                _lobby.Login(_nickname);
            };
            _client.Disconnected += reason =>
            {
                _status = "disconnected: " + reason;
                Debug.LogWarning("[net] disconnected: " + reason);
            };

            _lobby.LoginCompleted += (result, player) =>
            {
                if (result != ResultCode.ResultOk)
                {
                    _status = "login failed: " + result;
                    Debug.LogWarning("[net] login failed: " + result);
                    return;
                }
                _status = "logged in as " + player.Nickname + " (id " + player.PlayerId + ")";
                _lobby.JoinRoom(roomId);
            };
            _lobby.RoomJoinCompleted += response =>
            {
                if (response.Result != ResultCode.ResultOk)
                {
                    _status = "join room failed: " + response.Result;
                    Debug.LogWarning("[net] join room failed: " + response.Result);
                    return;
                }
                _roomInfo = "room " + response.RoomId + ": " + response.Players.Count + " player(s)";
                Debug.Log("[net] joined " + _roomInfo);
            };
            _lobby.OtherPlayerJoined += player =>
            {
                Debug.Log("[net] player joined: " + player.Nickname);
            };
            _lobby.OtherPlayerLeft += playerId =>
            {
                Debug.Log("[net] player left: " + playerId);
            };

            _client.Connect(host, port);
        }

        private void Update()
        {
            if (_client != null) _client.Tick();
        }

        private void OnDestroy()
        {
            // 플레이를 멈출 때 소켓과 수신 스레드를 정리한다.
            if (_client != null) _client.Dispose();
        }

        private void OnGUI()
        {
            if (_client == null) return;
            GUILayout.Label("Server: " + _status);
            if (_roomInfo.Length > 0) GUILayout.Label(_roomInfo);
            if (_client.IsConnected)
            {
                GUILayout.Label("RTT: " + _client.LastRttMs.ToString("F1") + " ms (pongs " + _client.PongCount + ")");
            }
        }
    }
}
