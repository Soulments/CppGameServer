using System;
using System.Collections.Generic;

namespace CppGameServer.Sync
{
    /// <summary>스냅샷에 담긴 한 플레이어의 상태.</summary>
    public struct SnapshotPlayer
    {
        public ulong Id;
        public float X;
        public float Z;
        public uint LastInputSeq;

        public SnapshotPlayer(ulong id, float x, float z, uint lastInputSeq)
        {
            Id = id;
            X = x;
            Z = z;
            LastInputSeq = lastInputSeq;
        }
    }

    /// <summary>보간 결과: 지금 화면에 그려야 할 플레이어 위치.</summary>
    public struct PlayerSample
    {
        public ulong Id;
        public float X;
        public float Z;

        public PlayerSample(ulong id, float x, float z)
        {
            Id = id;
            X = x;
            Z = z;
        }
    }

    /// <summary>
    /// 서버 스냅샷(20Hz)을 받아서 다른 플레이어를 부드럽게 보여 주는 보간기. Unity API 에 의존하지 않는 순수 C# 이다.
    ///
    /// 동작 요약
    ///  - 렌더링을 InterpolationDelay(기본 100ms = 2틱)만큼 과거로 늦춰서, 항상 두 스냅샷 사이를 보간한다.
    ///  - 스냅샷이 끊겨서 렌더 시각이 마지막 스냅샷을 넘으면 마지막 속도로 최대 MaxExtrapolation(250ms)까지 외삽하고 그 뒤에는 멈춘다.
    ///  - 서버 시각 추정: 스냅샷마다 (도착 시각 - 서버 틱 시각) 을 구해서 최근 40개(2초) 중 최솟값을 시계 오프셋으로 쓴다.
    ///    가장 덜 지연된 패킷을 기준으로 삼아서 도착 지터(TCP 정체 등)에 흔들리지 않는다.
    ///  - 렌더 시계는 실제 경과 시간만큼 전진하고, 목표와 어긋나면 ±10% 속도로만 천천히 보정한다.
    ///    그래서 시계가 거꾸로 가지 않고(캐릭터가 뒤로 튀지 않음), 크게 뒤처졌을 때만 한 번에 따라잡는다.
    ///
    /// 시각은 모두 호출하는 쪽이 넘긴다(now). 단조 증가하는 초 단위 시계를 쓰면 되고(Unity 는 Time.realtimeSinceStartupAsDouble),
    /// 서버 시계와 같을 필요는 없다.
    /// </summary>
    public sealed class SnapshotInterpolator
    {
        /// <summary>서버 틱 간격. server/src/game/Simulation.h 의 kTickRate(20)와 같아야 한다.</summary>
        public const double TickSeconds = 1.0 / 20.0;

        /// <summary>외삽할 때 위치를 제한하는 아레나 반경. Simulation.h 의 kArenaHalfSize 와 같다.</summary>
        public const float ArenaHalfSize = 20.0f;

        private const int OffsetWindow = 40;          // 시계 오프셋을 구할 스냅샷 수 (2초)
        private const int MaxBuffered = 64;           // 보관할 스냅샷 수 (약 3.2초)
        private const double SlewRate = 0.1;          // 렌더 시계 보정 속도 (±10%)
        private const double SnapForward = 0.25;      // 이만큼 이상 뒤처지면 한 번에 따라잡는다
        private const double SnapBackward = 1.0;      // 이만큼 이상 앞서가면(서버 재시작 등) 한 번에 되돌린다
        private const uint RestartTickGap = 100;      // 틱 번호가 이보다 크게 줄면 서버가 다시 시작한 것으로 본다

        private struct Frame
        {
            public uint Tick;
            public double Time;
            public SnapshotPlayer[] Players;
        }

        private readonly List<Frame> _frames = new List<Frame>();
        private readonly Queue<double> _offsets = new Queue<double>();
        private double _offset;
        private bool _hasClock;
        private double _renderTime;
        private double _lastNow;

        /// <summary>렌더링을 서버 시각보다 늦추는 시간(초). 늘리면 지터에 강해지고 반응은 느려진다.</summary>
        public double InterpolationDelay { get; set; } = 0.1;

        /// <summary>스냅샷이 끊겼을 때 마지막 속도로 이동시킬 최대 시간(초).</summary>
        public double MaxExtrapolation { get; set; } = 0.25;

        /// <summary>직전 TrySample 이 외삽 결과였는지.</summary>
        public bool IsExtrapolating { get; private set; }

        /// <summary>현재 렌더 시각(서버 시각 기준 초).</summary>
        public double RenderTime { get { return _renderTime; } }

        public int BufferedCount { get { return _frames.Count; } }

        /// <summary>스냅샷 1개를 보관한다. arrivalTime 은 받은 시각(호출하는 쪽의 시계).</summary>
        public void AddSnapshot(uint tick, IList<SnapshotPlayer> players, double arrivalTime)
        {
            if (_frames.Count > 0)
            {
                uint last = _frames[_frames.Count - 1].Tick;
                if (tick <= last)
                {
                    if (last - tick > RestartTickGap)
                    {
                        Clear();  // 서버가 다시 시작해서 틱이 처음으로 돌아갔다
                    }
                    else
                    {
                        return;  // 중복이거나 순서가 뒤바뀐 스냅샷은 버린다
                    }
                }
            }

            double tickTime = tick * TickSeconds;
            _offsets.Enqueue(arrivalTime - tickTime);
            while (_offsets.Count > OffsetWindow) _offsets.Dequeue();

            double min = double.MaxValue;
            foreach (double o in _offsets)
            {
                if (o < min) min = o;
            }
            _offset = min;

            var copy = new SnapshotPlayer[players.Count];
            for (int i = 0; i < copy.Length; i++) copy[i] = players[i];

            _frames.Add(new Frame { Tick = tick, Time = tickTime, Players = copy });
            if (_frames.Count > MaxBuffered) _frames.RemoveAt(0);
        }

        /// <summary>
        /// now 시점에 그릴 위치를 output 에 채운다 (기존 내용은 지운다). 보관한 스냅샷이 없으면 false.
        /// 매 프레임 now 가 줄어들지 않게 호출해야 한다.
        /// </summary>
        public bool TrySample(double now, List<PlayerSample> output)
        {
            output.Clear();
            IsExtrapolating = false;
            if (_frames.Count == 0) return false;

            UpdateClock(now);
            double rt = _renderTime;
            int last = _frames.Count - 1;

            if (rt <= _frames[0].Time)
            {
                EmitFrame(_frames[0], output);  // 아직 버퍼가 덜 찼다: 첫 스냅샷 위치에 그대로 둔다
                return true;
            }
            if (rt >= _frames[last].Time)
            {
                Extrapolate(rt, output);
                return true;
            }

            int a = last - 1;
            while (a > 0 && _frames[a].Time > rt) a--;
            Frame from = _frames[a];
            Frame to = _frames[a + 1];
            double alpha = (rt - from.Time) / (to.Time - from.Time);

            // 도착 시점의 플레이어(to)를 기준으로 그린다. from 에 없던 새 플레이어는 보간 없이 to 위치를 쓰고,
            // to 에 없는(나간) 플레이어는 그리지 않는다.
            for (int i = 0; i < to.Players.Length; i++)
            {
                SnapshotPlayer target = to.Players[i];
                int j = IndexOf(from.Players, target.Id);
                if (j < 0)
                {
                    output.Add(new PlayerSample(target.Id, target.X, target.Z));
                }
                else
                {
                    SnapshotPlayer origin = from.Players[j];
                    output.Add(new PlayerSample(
                        target.Id,
                        (float)(origin.X + (target.X - origin.X) * alpha),
                        (float)(origin.Z + (target.Z - origin.Z) * alpha)));
                }
            }
            return true;
        }

        public void Clear()
        {
            _frames.Clear();
            _offsets.Clear();
            _hasClock = false;
            IsExtrapolating = false;
        }

        private void UpdateClock(double now)
        {
            double target = now - _offset - InterpolationDelay;
            if (!_hasClock)
            {
                _renderTime = target;
                _lastNow = now;
                _hasClock = true;
                return;
            }

            double elapsed = now - _lastNow;
            if (elapsed < 0) elapsed = 0;
            _lastNow = now;

            double expected = _renderTime + elapsed;
            double error = target - expected;  // 양수면 렌더 시계가 목표보다 느리다
            if (error > SnapForward || error < -SnapBackward)
            {
                _renderTime = target;
            }
            else
            {
                double limit = SlewRate * elapsed;
                double slew = Math.Max(-limit, Math.Min(limit, error));
                _renderTime = expected + slew;
            }
        }

        private void Extrapolate(double rt, List<PlayerSample> output)
        {
            int last = _frames.Count - 1;
            Frame latest = _frames[last];
            bool hasPrevious = last > 0;
            Frame previous = hasPrevious ? _frames[last - 1] : latest;

            double beyond = rt - latest.Time;
            IsExtrapolating = beyond > 0;
            double extra = Math.Min(Math.Max(beyond, 0), MaxExtrapolation);
            double span = latest.Time - previous.Time;

            for (int i = 0; i < latest.Players.Length; i++)
            {
                SnapshotPlayer p = latest.Players[i];
                double x = p.X;
                double z = p.Z;

                int j = hasPrevious && span > 0 ? IndexOf(previous.Players, p.Id) : -1;
                if (j >= 0)
                {
                    double vx = (p.X - previous.Players[j].X) / span;
                    double vz = (p.Z - previous.Players[j].Z) / span;
                    x += vx * extra;
                    z += vz * extra;
                }

                output.Add(new PlayerSample(p.Id, Clamp(x), Clamp(z)));
            }
        }

        private static float Clamp(double value)
        {
            return (float)Math.Max(-ArenaHalfSize, Math.Min(ArenaHalfSize, value));
        }

        private static void EmitFrame(Frame frame, List<PlayerSample> output)
        {
            for (int i = 0; i < frame.Players.Length; i++)
            {
                SnapshotPlayer p = frame.Players[i];
                output.Add(new PlayerSample(p.Id, p.X, p.Z));
            }
        }

        private static int IndexOf(SnapshotPlayer[] players, ulong id)
        {
            for (int i = 0; i < players.Length; i++)
            {
                if (players[i].Id == id) return i;
            }
            return -1;
        }
    }
}
