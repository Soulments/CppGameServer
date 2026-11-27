using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using CppGameServer.Network;
using CppGameServer.Protocol;
using CppGameServer.Sync;

// 클라이언트 로직 검증 (Unity 에디터 불필요).
//   unit          보간기와 입력 전송 규칙의 단위 테스트 (서버 불필요)
//   e2e <port>    실행 중인 서버에 클라이언트 2개를 붙여 보간과 입력 전송을 확인
public static class Program
{
    private static int _failures;
    private static int _checks;

    private static void Check(bool condition, string message)
    {
        _checks++;
        if (!condition)
        {
            _failures++;
            Console.WriteLine("FAIL  " + message);
        }
    }

    private static void Run(string name, Action test)
    {
        int before = _failures;
        try
        {
            test();
        }
        catch (Exception e)
        {
            _failures++;
            Console.WriteLine("FAIL  " + name + ": exception " + e);
        }
        Console.WriteLine((_failures == before ? "PASS  " : "FAIL  ") + name);
    }

    public static int Main(string[] args)
    {
        string mode = args.Length > 0 ? args[0] : "unit";
        if (mode == "unit")
        {
            RunUnitTests();
        }
        else if (mode == "e2e" && args.Length > 1)
        {
            Run("e2e: two clients, interpolation and input", () => RunE2E(int.Parse(args[1])));
        }
        else
        {
            Console.WriteLine("usage: ClientTests unit | e2e <port>");
            return 2;
        }

        Console.WriteLine(_failures == 0
            ? "\nall client tests passed (" + _checks + " checks)"
            : "\n" + _failures + " failure(s)");
        return _failures == 0 ? 0 : 1;
    }

    // ---------------------------------------------------------------------------------------------
    // 합성 스냅샷 스트림: 플레이어 1명이 서버 시각 t 에서 x = -9 + 1.5 * t 로 +x 방향 등속 이동한다.
    // (서버 틱 k 의 시각 = k * 0.05). 위치가 시간의 1차 함수라서 보간 결과를 정확히 계산할 수 있고,
    // 10초까지 아레나(±20) 안에 머물러서 외삽 위치 제한이 결과에 끼어들지 않는다.
    // ---------------------------------------------------------------------------------------------

    private const double Dt = SnapshotInterpolator.TickSeconds;
    private const double Speed = 1.5;

    /// <summary>서버 시각 t 에서의 위치.</summary>
    private static double PosAt(double serverTime)
    {
        return -9.0 + Speed * serverTime;
    }

    private static SnapshotPlayer[] Mover(uint tick, ulong id = 1)
    {
        return new[] { new SnapshotPlayer(id, (float)PosAt(tick * Dt), 0f, 0) };
    }

    private static float XOf(List<PlayerSample> samples, ulong id = 1)
    {
        foreach (PlayerSample s in samples)
        {
            if (s.Id == id) return s.X;
        }
        throw new InvalidOperationException("player " + id + " not sampled");
    }

    private static bool Has(List<PlayerSample> samples, ulong id)
    {
        foreach (PlayerSample s in samples)
        {
            if (s.Id == id) return true;
        }
        return false;
    }

    /// <summary>
    /// 스냅샷이 도착하는 시각을 arrival(tick) 으로 정하고, 로컬 시계를 60fps 로 돌리면서 매 프레임 샘플링한다.
    /// 각 프레임에서 도착 시각이 now 이하인 스냅샷을 먼저 전달한다.
    /// </summary>
    private static void Simulate(SnapshotInterpolator interp, Func<uint, double> arrival, double start, double end,
                                 uint lastTick, Action<double, List<PlayerSample>, bool> onFrame, Func<uint, SnapshotPlayer[]> make = null)
    {
        make = make ?? (tick => Mover(tick));
        var samples = new List<PlayerSample>();
        uint next = 1;
        for (double now = start; now <= end; now += 1.0 / 60.0)
        {
            while (next <= lastTick && arrival(next) <= now)
            {
                interp.AddSnapshot(next, make(next), arrival(next));
                next++;
            }
            bool ok = interp.TrySample(now, samples);
            onFrame(now, samples, ok);
        }
    }

    private static void RunUnitTests()
    {
        Run("empty interpolator returns nothing", () =>
        {
            var interp = new SnapshotInterpolator();
            var samples = new List<PlayerSample>();
            Check(!interp.TrySample(1.0, samples) && samples.Count == 0, "no snapshot -> false");
        });

        Run("first snapshot is shown as is", () =>
        {
            var interp = new SnapshotInterpolator();
            var samples = new List<PlayerSample>();
            interp.AddSnapshot(5, new[] { new SnapshotPlayer(7, 3f, -2f, 0) }, 10.0);
            Check(interp.TrySample(10.0, samples), "sampled");
            Check(samples.Count == 1 && samples[0].X == 3f && samples[0].Z == -2f, "position of the only snapshot");
        });

        Run("steady stream: exact interpolation with 100ms delay, independent of the local clock origin", () =>
        {
            foreach (double origin in new[] { 0.0, 1234.5, 987654.25 })
            {
                var interp = new SnapshotInterpolator();
                const double net = 0.03;
                double maxError = 0;
                int extrapolating = 0, measured = 0;
                Simulate(interp, k => origin + k * Dt + net, origin + 0.2, origin + 9.5, 200, (now, s, ok) =>
                {
                    if (!ok || now < origin + 1.5) return;  // 시계가 안정된 뒤부터 본다
                    double expected = PosAt(now - origin - net - 0.1);  // 서버 시각 (now - origin - net) 보다 100ms 과거
                    maxError = Math.Max(maxError, Math.Abs(XOf(s) - expected));
                    measured++;
                    if (interp.IsExtrapolating) extrapolating++;
                });
                Check(measured > 300, "measured frames (origin " + origin + "): " + measured);
                Check(maxError < 2e-3, "max error " + maxError + " (origin " + origin + ")");
                Check(extrapolating == 0, "no extrapolation in a steady stream (origin " + origin + ")");
            }
        });

        Run("arrival jitter up to 40ms: no extrapolation, no backward movement, small error", () =>
        {
            var interp = new SnapshotInterpolator();
            var rng = new Random(42);
            var jitter = new double[400];
            for (int i = 0; i < jitter.Length; i++) jitter[i] = rng.NextDouble() * 0.04;
            const double net = 0.02;
            float previous = float.MinValue;
            double maxError = 0;
            int extrapolating = 0, measured = 0;
            bool backward = false;
            Simulate(interp, k => k * Dt + net + jitter[k], 0.2, 12.0, 300, (now, s, ok) =>
            {
                if (!ok || now < 2.0) return;
                float x = XOf(s);
                if (x < previous - 1e-5f) backward = true;
                previous = x;
                double ideal = PosAt(now - net - 0.1);
                maxError = Math.Max(maxError, Math.Abs(x - ideal));
                measured++;
                if (interp.IsExtrapolating) extrapolating++;
            });
            Check(measured > 400, "measured frames: " + measured);
            Check(!backward, "position never moved backward");
            Check(extrapolating == 0, "frames extrapolating: " + extrapolating);
            Check(maxError < Speed * 0.01, "max error " + maxError + " (<= 10ms of movement)");
        });

        Run("base latency +80ms: the render clock slews instead of rewinding", () =>
        {
            // 5초 무렵 기본 지연이 20ms -> 100ms 로 늘어난다. 시계 오프셋(최근 2초의 최솟값)은 옛 값이 창에서 빠지는 순간
            // 한 번에 80ms 바뀌는데, 렌더 시계를 그대로 따라 움직이면 캐릭터가 뒤로 튄다.
            var interp = new SnapshotInterpolator();
            float previous = float.MinValue;
            bool backward = false;
            double maxStep = 0, finalError = 0;
            Simulate(interp, k => k * Dt + (k < 100 ? 0.02 : 0.10), 0.2, 12.0, 220, (now, s, ok) =>
            {
                if (!ok || now < 2.0) return;
                float x = XOf(s);
                if (x < previous - 1e-5f) backward = true;
                if (previous != float.MinValue) maxStep = Math.Max(maxStep, x - previous);
                previous = x;
                if (now > 10.0 && now < 10.5) finalError = Math.Max(finalError, Math.Abs(x - PosAt(now - 0.10 - 0.1)));  // 스트림이 계속 오는 구간
            });
            Check(!backward, "no backward movement when the offset estimate jumps");
            Check(maxStep < Speed / 60.0 * 1.3, "max per-frame step " + maxStep + " (no jump)");
            Check(finalError < 5e-3, "settled on the new latency: error " + finalError);
        });

        Run("200ms TCP stall: extrapolates through it, never moves backward, never jumps", () =>
        {
            var interp = new SnapshotInterpolator();
            const double net = 0.02;
            // 5.0초에 보낸 스냅샷부터 5.2초에 몰아서 도착한다 (정체 후 한꺼번에 전달)
            Func<uint, double> arrival = k =>
            {
                double normal = k * Dt + net;
                return normal >= 5.0 && normal < 5.2 ? 5.2 : normal;
            };
            float previous = float.MinValue;
            bool backward = false;
            double maxStep = 0;
            int extrapolating = 0;
            Simulate(interp, arrival, 0.2, 9.0, 200, (now, s, ok) =>
            {
                if (!ok || now < 2.0) return;
                float x = XOf(s);
                if (x < previous - 1e-5f) backward = true;
                if (previous != float.MinValue) maxStep = Math.Max(maxStep, x - previous);
                previous = x;
                if (interp.IsExtrapolating) extrapolating++;
            });
            Check(!backward, "no backward movement");
            Check(extrapolating >= 3, "extrapolated while stalled: " + extrapolating + " frames");
            Check(maxStep < Speed / 60.0 * 1.3, "max per-frame step " + maxStep + " (no teleport)");
        });

        Run("600ms stall: holds after 250ms of extrapolation, then recovers without moving backward", () =>
        {
            var interp = new SnapshotInterpolator();
            Func<uint, double> arrival = k =>
            {
                double normal = k * Dt;
                return normal >= 5.0 && normal < 5.6 ? 5.6 : normal;
            };
            float previous = float.MinValue;
            bool backward = false;
            int heldFrames = 0;
            double lastErrorAfterRecovery = 0;
            Simulate(interp, arrival, 0.2, 10.0, 200, (now, s, ok) =>
            {
                if (!ok || now < 2.0) return;
                float x = XOf(s);
                if (x < previous - 1e-5f) backward = true;
                if (now > 5.45 && now < 5.55 && Math.Abs(x - previous) < 1e-6f) heldFrames++;  // 외삽 한계 이후 멈춤
                previous = x;
                if (now > 9.0) lastErrorAfterRecovery = Math.Abs(x - PosAt(now - 0.1));
            });
            Check(!backward, "no backward movement");
            Check(heldFrames >= 3, "position held after the extrapolation limit: " + heldFrames + " frames");
            Check(lastErrorAfterRecovery < 0.05, "back on track after recovery: error " + lastErrorAfterRecovery);
        });

        Run("extrapolation stops at MaxExtrapolation", () =>
        {
            var interp = new SnapshotInterpolator();
            var samples = new List<PlayerSample>();
            for (uint k = 1; k <= 40; k++) interp.AddSnapshot(k, Mover(k), k * Dt);
            // 마지막 스냅샷(tick 40, x = 10) 이후 아무것도 오지 않은 채 한참 지난 시각
            interp.TrySample(40 * Dt + 0.1, samples);   // 시계 초기화 (렌더 시각 = 마지막 틱 시각)
            interp.TrySample(40 * Dt + 0.1 + 5.0, samples);
            float x = XOf(samples);
            float last = (float)PosAt(40 * Dt);
            Check(interp.IsExtrapolating, "flagged as extrapolating");
            Check(Math.Abs(x - (last + Speed * 0.25)) < 1e-3, "advanced exactly MaxExtrapolation (250ms) past the last snapshot: x = " + x);
        });

        Run("extrapolation never leaves the arena", () =>
        {
            var interp = new SnapshotInterpolator();
            var samples = new List<PlayerSample>();
            interp.AddSnapshot(1, new[] { new SnapshotPlayer(1, 19.5f, 0f, 0) }, 0.05);
            interp.AddSnapshot(2, new[] { new SnapshotPlayer(1, 19.75f, 0f, 0) }, 0.10);
            interp.TrySample(0.10, samples);
            interp.TrySample(0.10 + 0.5, samples);
            Check(XOf(samples) <= SnapshotInterpolator.ArenaHalfSize + 1e-4f, "x = " + XOf(samples));
        });

        Run("players joining and leaving", () =>
        {
            var interp = new SnapshotInterpolator();
            var samples = new List<PlayerSample>();
            Func<uint, SnapshotPlayer[]> make = tick =>
            {
                var list = new List<SnapshotPlayer> { new SnapshotPlayer(1, tick * 0.1f, 0f, 0) };
                if (tick >= 20 && tick < 40) list.Add(new SnapshotPlayer(2, 5f, 5f, 0));  // 2번은 틱 20~39 동안만 있다
                return list.ToArray();
            };
            bool sawJoinAtItsPosition = true, bornOnlyAfterJoin = true, goneAfterLeave = true;
            int withB = 0;
            Simulate(interp, k => k * Dt, 0.2, 6.0, 120, (now, s, ok) =>
            {
                if (!ok || now < 1.0) return;
                double rt = interp.RenderTime;
                bool has = Has(s, 2);
                if (has) { withB++; if (Math.Abs(s.Find(p => p.Id == 2).X - 5f) > 1e-4f) sawJoinAtItsPosition = false; }
                if (rt < 19 * Dt && has) bornOnlyAfterJoin = false;
                if (rt > 40 * Dt && has) goneAfterLeave = false;
            }, make);
            Check(withB > 30, "player 2 was drawn while present: " + withB + " frames");
            Check(sawJoinAtItsPosition, "a new player appears at its own position, not interpolated from nowhere");
            Check(bornOnlyAfterJoin, "no player before it joined");
            Check(goneAfterLeave, "player removed after leaving");
        });

        Run("duplicate and out-of-order snapshots are ignored; server restart clears the buffer", () =>
        {
            var interp = new SnapshotInterpolator();
            interp.AddSnapshot(500, Mover(500), 1.0);
            interp.AddSnapshot(501, Mover(501), 1.05);
            interp.AddSnapshot(501, Mover(501), 1.06);  // 중복
            interp.AddSnapshot(499, Mover(499), 1.07);  // 순서가 뒤바뀜
            Check(interp.BufferedCount == 2, "buffered " + interp.BufferedCount);
            interp.AddSnapshot(3, Mover(3), 20.0);  // 틱이 100 넘게 줄었다: 서버 재시작
            Check(interp.BufferedCount == 1, "buffer restarted: " + interp.BufferedCount);
        });

        Run("larger InterpolationDelay shows an older position", () =>
        {
            var a = new SnapshotInterpolator();
            var b = new SnapshotInterpolator { InterpolationDelay = 0.2 };
            var sa = new List<PlayerSample>();
            var sb = new List<PlayerSample>();
            double diff = 0;
            int n = 0;
            uint next = 1;
            for (double now = 0.1; now < 6.0; now += 1.0 / 60.0)
            {
                while (next <= 100 && next * Dt <= now)
                {
                    a.AddSnapshot(next, Mover(next), next * Dt);
                    b.AddSnapshot(next, Mover(next), next * Dt);
                    next++;
                }
                a.TrySample(now, sa);
                b.TrySample(now, sb);
                if (now > 2.0 && now < 4.8) { diff += XOf(sa) - XOf(sb); n++; }
            }
            Check(n > 100 && Math.Abs(diff / n - Speed * 0.1) < 5e-3, "100ms more delay = " + Speed * 0.1 + " units behind: " + diff / n);
        });

        Run("MoveInputSender sends only on change, numbers inputs, retries failures", () =>
        {
            var sent = new List<string>();
            bool connected = false;
            var sender = new MoveInputSender((seq, x, z) =>
            {
                if (!connected) return false;
                sent.Add(seq + ":" + x + "," + z);
                return true;
            });

            Check(!sender.Update(0, 0), "no change from the initial (0, 0): nothing to send");
            Check(!sender.Update(1, 0) && sender.LastSeq == 0, "not connected: send fails and state is not committed");
            connected = true;
            Check(sender.Update(1, 0) && sender.LastSeq == 1, "retried with the same seq 1");
            Check(!sender.Update(1, 0), "same input is not sent again");
            Check(!sender.Update(1, 0.0001f), "tiny change is not sent");
            Check(sender.Update(1, 1) && sender.LastSeq == 2, "changed input is sent as seq 2");
            Check(!sender.Update(float.NaN, 0) && !sender.Update(0, float.PositiveInfinity), "non-finite input is never sent");
            Check(sender.Update(0, 0) && sender.LastSeq == 3, "release sends (0, 0) as seq 3");
            Check(!sender.Update(0, 0), "stays stopped");
            Check(string.Join(" ", sent) == "1:1,0 2:1,1 3:0,0", "sent: " + string.Join(" ", sent));
        });
    }

    // ---------------------------------------------------------------------------------------------
    // e2e: 실제 서버와 클라이언트 2개
    // ---------------------------------------------------------------------------------------------

    private sealed class Peer
    {
        public readonly GameClient Client = new GameClient();
        public readonly LobbyClient Lobby;
        public bool Connected;
        public ResultCode? LoginResult;
        public ulong PlayerId;
        public JoinRoomResponse Room;
        public int SnapshotCount;
        public WorldSnapshot Latest;
        public readonly List<string> Disconnects = new List<string>();
        public SnapshotInterpolator Interpolator;
        public Func<double> Clock;

        public Peer(int port)
        {
            Client.PingIntervalSeconds = 1.0;
            Lobby = new LobbyClient(Client);
            Client.Connected += () => Connected = true;
            Client.Disconnected += r => Disconnects.Add(r);
            Lobby.LoginCompleted += (r, p) => { LoginResult = r; if (p != null) PlayerId = p.PlayerId; };
            Lobby.RoomJoinCompleted += r => Room = r;
            Lobby.SnapshotReceived += snap =>
            {
                SnapshotCount++;
                Latest = snap;
                if (Interpolator != null)
                {
                    var players = new List<SnapshotPlayer>();
                    foreach (PlayerSnapshot p in snap.Players)
                    {
                        players.Add(new SnapshotPlayer(p.PlayerId, p.X, p.Z, p.LastInputSeq));
                    }
                    Interpolator.AddSnapshot(snap.Tick, players, Clock());
                }
            };
            Client.Connect("127.0.0.1", port);
        }
    }

    private static bool PumpUntil(Func<bool> done, double seconds, params Peer[] peers)
    {
        var end = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < end)
        {
            foreach (Peer p in peers) p.Client.Tick();
            if (done()) return true;
            Thread.Sleep(5);
        }
        return false;
    }

    private static float LatestX(Peer peer, ulong id)
    {
        foreach (PlayerSnapshot p in peer.Latest.Players)
        {
            if (p.PlayerId == id) return p.X;
        }
        throw new InvalidOperationException("player not in latest snapshot");
    }

    private static void RunE2E(int port)
    {
        var clockWatch = Stopwatch.StartNew();
        Func<double> clock = () => clockWatch.Elapsed.TotalSeconds;

        var a = new Peer(port);
        var b = new Peer(port) { Interpolator = new SnapshotInterpolator(), Clock = clock };
        Check(PumpUntil(() => a.Connected && b.Connected, 5, a, b), "both clients connected");

        string suffix = (DateTime.UtcNow.Ticks % 1000000).ToString();
        a.Lobby.Login("ea" + suffix);
        b.Lobby.Login("eb" + suffix);
        Check(PumpUntil(() => a.LoginResult.HasValue && b.LoginResult.HasValue, 3, a, b)
              && a.LoginResult == ResultCode.ResultOk && b.LoginResult == ResultCode.ResultOk, "both logged in");

        uint room = 600 + (uint)new Random().Next(0, 300);
        a.Lobby.JoinRoom(room);
        b.Lobby.JoinRoom(room);
        Check(PumpUntil(() => a.Room != null && b.Room != null, 3, a, b)
              && a.Room.Result == ResultCode.ResultOk && b.Room.Result == ResultCode.ResultOk, "both joined room " + room);

        Check(PumpUntil(() => a.SnapshotCount > 10 && b.SnapshotCount > 10 && b.Latest.Players.Count == 2, 3, a, b),
              "both receive snapshots with 2 players");

        // A 가 +x 로 움직이고, B 의 보간기가 그 움직임을 어떻게 보여 주는지 본다
        var sender = new MoveInputSender((seq, x, z) => a.Lobby.SendMoveInput(seq, x, z));
        var samples = new List<PlayerSample>();
        float startX = LatestX(b, a.PlayerId);
        Check(sender.Update(1f, 0f), "input sent");

        var series = new List<float>();
        int frames = 0, extrapolating = 0;
        double maxStep = 0;
        double lagSum = 0;
        int lagCount = 0;
        double begin = clock();
        while (clock() - begin < 3.0)
        {
            a.Client.Tick();
            b.Client.Tick();
            double now = clock();
            if (b.Interpolator.TrySample(now, samples))
            {
                float x = XOf(samples, a.PlayerId);
                if (series.Count > 0) maxStep = Math.Max(maxStep, x - series[series.Count - 1]);
                series.Add(x);
                frames++;
                if (b.Interpolator.IsExtrapolating) extrapolating++;
                if (now - begin > 1.0)
                {
                    lagSum += LatestX(b, a.PlayerId) - x;  // 방금 받은 최신 서버 위치보다 얼마나 뒤에서 그리는가
                    lagCount++;
                }
            }
            Thread.Sleep(16);
        }

        bool monotonic = true;
        for (int i = 1; i < series.Count; i++) if (series[i] < series[i - 1] - 1e-5f) monotonic = false;
        double moved = series[series.Count - 1] - series[0];
        double lag = lagSum / Math.Max(1, lagCount);
        Console.WriteLine("  e2e metrics: moved " + moved.ToString("F2") + " units, lag behind latest server position " + lag.ToString("F2")
                          + " units (~" + (lag / 5.0 * 1000).ToString("F0") + " ms), extrapolating " + extrapolating + "/" + frames
                          + " frames, max per-frame step " + maxStep.ToString("F3"));
        Check(monotonic, "B draws A's movement monotonically");
        Check(moved > 6.0, "A visibly moved on B's screen: " + moved.ToString("F2") + " units in 3s (expected about 14)");
        Check(lag > 0.3 && lag < 1.2, "B draws A behind the newest received snapshot (100ms delay minus that snapshot's age, expected 0.3-1.2 units): " + lag.ToString("F2"));
        Check(extrapolating * 20 <= frames, "extrapolating frames: " + extrapolating + " / " + frames);
        Check(maxStep < 5.0 * 0.05 * 1.5, "no jumps: max per-frame step " + maxStep.ToString("F3"));
        Check(LatestX(b, a.PlayerId) > startX + 6.0f, "server position advanced as well");

        // 멈추면 B 에서도 멈춘다
        Check(sender.Update(0f, 0f), "stop input sent");
        double stopBegin = clock();
        var tail = new List<float>();
        while (clock() - stopBegin < 1.0)
        {
            a.Client.Tick();
            b.Client.Tick();
            if (b.Interpolator.TrySample(clock(), samples) && clock() - stopBegin > 0.6) tail.Add(XOf(samples, a.PlayerId));
            Thread.Sleep(16);
        }
        bool still = tail.Count > 5;
        for (int i = 1; i < tail.Count; i++) if (Math.Abs(tail[i] - tail[i - 1]) > 1e-3f) still = false;
        Check(still, "A stopped on B's screen after the stop input (" + tail.Count + " frames)");

        Check(a.Disconnects.Count == 0 && b.Disconnects.Count == 0, "no unexpected disconnects");
        a.Client.Dispose();
        b.Client.Dispose();
    }
}
