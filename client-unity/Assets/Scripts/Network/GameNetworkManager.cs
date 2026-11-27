using UnityEngine;

namespace CppGameServer.Network
{
    /// <summary>
    /// 씬의 빈 GameObject 에 붙여서 쓴다. 시작할 때 서버에 접속하고 하트비트(Ping/Pong)를 유지한다.
    /// 클라이언트 2개 테스트: 에디터 + 빌드를 같이 실행하거나 빌드를 2개 실행한다.
    /// </summary>
    public class GameNetworkManager : MonoBehaviour
    {
        [SerializeField] private string host = "127.0.0.1";
        [SerializeField] private int port = 7777;
        [SerializeField] private float pingIntervalSeconds = 3f;

        private GameClient _client;
        private string _status = "connecting...";

        private void Awake()
        {
            // 포커스를 잃어도(다른 클라이언트 창을 눌러도) 하트비트가 끊기지 않게 한다.
            Application.runInBackground = true;
        }

        private void Start()
        {
            _client = new GameClient();
            _client.PingIntervalSeconds = pingIntervalSeconds;
            _client.Connected += () =>
            {
                _status = "connected";
                Debug.Log("[net] connected to " + host + ":" + port);
            };
            _client.Disconnected += reason =>
            {
                _status = "disconnected: " + reason;
                Debug.LogWarning("[net] disconnected: " + reason);
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
            if (_client.IsConnected)
            {
                GUILayout.Label("RTT: " + _client.LastRttMs.ToString("F1") + " ms (pongs " + _client.PongCount + ")");
            }
        }
    }
}
