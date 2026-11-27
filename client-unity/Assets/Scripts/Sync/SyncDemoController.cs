using System.Collections.Generic;
using CppGameServer.Network;
using CppGameServer.Protocol;
using UnityEngine;

namespace CppGameServer.Sync
{
    /// <summary>
    /// 이동 동기화 데모. GameNetworkManager 와 **같은 GameObject** 에 붙이면 된다 (씬이나 프리팹이 필요 없다).
    ///
    /// - 입력(WASD/방향키)을 MoveInputSender 로 서버에 보낸다. 위치가 아니라 입력을 보낸다.
    /// - 서버 스냅샷을 SnapshotInterpolator 에 넣고, 보간한 위치에 플레이어마다 큐브를 만들어 움직인다.
    /// - 이 브랜치에서는 내 캐릭터도 서버 스냅샷으로만 움직인다 (입력 후 왕복 지연 + 보간 지연만큼 늦게 반응).
    ///   클라이언트 예측은 다음 브랜치에서 추가한다.
    ///
    /// 카메라는 씬의 기본 카메라를 위에서 아래로(예: 위치 (0, 40, 0), 회전 (90, 0, 0)) 두면 아레나([-20, 20])가 보인다.
    /// 클라이언트 2개 확인: 에디터와 빌드를 같이 실행하면 서로 다른 큐브가 보인다.
    /// 주의: Unity 에디터에서 직접 확인하지 못했다. 컴파일은 UnityEngine 스텁으로 검사한다.
    /// </summary>
    [RequireComponent(typeof(GameNetworkManager))]
    public class SyncDemoController : MonoBehaviour
    {
        [SerializeField] private float interpolationDelaySeconds = 0.1f;

#pragma warning disable 0649  // 인스펙터에서 채워지는 필드
        [Tooltip("레거시 Input Manager 가 꺼진 프로젝트(Input System 패키지만 사용)에서는 이 값으로 이동을 시험한다.")]
        [SerializeField] private Vector2 debugInput;
#pragma warning restore 0649

        private readonly SnapshotInterpolator _interpolator = new SnapshotInterpolator();
        private readonly Dictionary<ulong, GameObject> _views = new Dictionary<ulong, GameObject>();
        private readonly List<PlayerSample> _samples = new List<PlayerSample>();
        private readonly List<ulong> _stale = new List<ulong>();

        private GameNetworkManager _network;
        private LobbyClient _subscribed;
        private MoveInputSender _sender;

        private void Awake()
        {
            _network = GetComponent<GameNetworkManager>();
        }

        private void Update()
        {
            EnsureSubscribed();
            if (_subscribed == null) return;  // GameNetworkManager.Start 가 아직 클라이언트를 만들지 않았다

            double now = Time.realtimeSinceStartupAsDouble;

            Vector2 input = ReadInput();
            _sender.Update(input.x, input.y);

            _interpolator.InterpolationDelay = interpolationDelaySeconds;
            if (_interpolator.TrySample(now, _samples))
            {
                ApplySamples();
            }
        }

        private void OnDestroy()
        {
            if (_subscribed != null) _subscribed.SnapshotReceived -= OnSnapshot;
        }

        private void OnGUI()
        {
            if (_subscribed == null) return;
            GUILayout.Label("Sync: " + _interpolator.BufferedCount + " snapshots buffered"
                            + (_interpolator.IsExtrapolating ? " (extrapolating)" : ""));
        }

        private void EnsureSubscribed()
        {
            LobbyClient lobby = _network.Lobby;
            if (lobby == null || lobby == _subscribed) return;

            if (_subscribed != null) _subscribed.SnapshotReceived -= OnSnapshot;
            _subscribed = lobby;
            _subscribed.SnapshotReceived += OnSnapshot;
            _sender = new MoveInputSender((seq, x, z) => lobby.SendMoveInput(seq, x, z));
            _interpolator.Clear();
        }

        private void OnSnapshot(WorldSnapshot snapshot)
        {
            var players = new List<SnapshotPlayer>(snapshot.Players.Count);
            foreach (PlayerSnapshot p in snapshot.Players)
            {
                players.Add(new SnapshotPlayer(p.PlayerId, p.X, p.Z, p.LastInputSeq));
            }
            // GameClient.Tick() 이 메인 스레드에서 이벤트를 전달하므로, 도착 시각은 그 프레임의 시각이다.
            // 프레임 단위 지터는 SnapshotInterpolator 의 최소 오프셋 필터가 흡수한다.
            _interpolator.AddSnapshot(snapshot.Tick, players, Time.realtimeSinceStartupAsDouble);
        }

        private Vector2 ReadInput()
        {
            Vector2 input = debugInput;
#if ENABLE_LEGACY_INPUT_MANAGER
            input += new Vector2(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));
#endif
            return Vector2.ClampMagnitude(input, 1f);
        }

        private void ApplySamples()
        {
            foreach (PlayerSample s in _samples)
            {
                GameObject view;
                if (!_views.TryGetValue(s.Id, out view))
                {
                    view = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    view.name = "Player " + s.Id;
                    _views[s.Id] = view;
                }
                view.transform.position = new Vector3(s.X, 0.5f, s.Z);
            }

            // 스냅샷에서 사라진(나간) 플레이어의 큐브를 지운다.
            _stale.Clear();
            foreach (KeyValuePair<ulong, GameObject> entry in _views)
            {
                bool present = false;
                foreach (PlayerSample s in _samples)
                {
                    if (s.Id == entry.Key) { present = true; break; }
                }
                if (!present) _stale.Add(entry.Key);
            }
            foreach (ulong id in _stale)
            {
                Destroy(_views[id]);
                _views.Remove(id);
            }
        }
    }
}
