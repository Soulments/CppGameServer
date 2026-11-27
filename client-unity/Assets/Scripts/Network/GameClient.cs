using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;

namespace CppGameServer.Network
{
    /// <summary>
    /// 서버 접속 클라이언트 (Unity API 에 의존하지 않는 순수 C#).
    ///
    /// - 접속과 수신은 백그라운드 스레드에서 하고, 이벤트는 Tick() 을 부르는 스레드(Unity 메인 스레드)에서 발생한다.
    /// - Tick() 이 PingIntervalSeconds 마다 Ping 을 보내고 Pong 으로 RTT 를 갱신한다.
    /// - 서버가 연결을 끊거나 오류가 나면 Disconnected 이벤트가 정확히 한 번 발생한다.
    /// </summary>
    public sealed class GameClient : IDisposable
    {
        public event Action Connected;
        public event Action<string> Disconnected;
        public event Action<ushort, byte[]> PacketReceived;

        public double PingIntervalSeconds = 3.0;

        public double LastRttMs { get; private set; }
        public int PongCount { get; private set; }

        public bool IsConnected
        {
            get { return _connected && _closedFlag == 0; }
        }

        private readonly ConcurrentQueue<Action> _mainThreadQueue = new ConcurrentQueue<Action>();
        private readonly object _sendLock = new object();
        private readonly Stopwatch _clock = Stopwatch.StartNew();

        private TcpClient _tcp;
        private NetworkStream _stream;
        private volatile bool _connected;
        private int _closedFlag;
        private double _nextPingAt;

        /// <summary>비동기로 접속을 시작한다. 결과는 Connected / Disconnected 이벤트로 받는다.</summary>
        public void Connect(string host, int port)
        {
            if (_tcp != null)
            {
                throw new InvalidOperationException("Connect() was already called");
            }

            _tcp = new TcpClient();
            _tcp.NoDelay = true;
            Task.Run(() => ConnectAndRead(host, port));
        }

        /// <summary>메인 스레드에서 매 프레임 호출한다. 이벤트를 전달하고 하트비트를 보낸다.</summary>
        public void Tick()
        {
            Action action;
            while (_mainThreadQueue.TryDequeue(out action))
            {
                action();
            }

            if (IsConnected)
            {
                double now = _clock.Elapsed.TotalSeconds;
                if (now >= _nextPingAt)
                {
                    _nextPingAt = now + PingIntervalSeconds;
                    SendPing();
                }
            }
        }

        public bool Send(ushort type, byte[] payload)
        {
            if (!IsConnected)
            {
                return false;
            }

            byte[] data = PacketProtocol.Encode(type, payload);
            try
            {
                lock (_sendLock)
                {
                    _stream.Write(data, 0, data.Length);
                }
                return true;
            }
            catch (Exception e)
            {
                Fail("send error: " + e.Message);
                return false;
            }
        }

        public void Disconnect()
        {
            Fail("disconnected by client");
        }

        public void Dispose()
        {
            Disconnect();
        }

        private void SendPing()
        {
            // payload 에 보낸 시각을 넣으면 서버가 그대로 되돌려 주므로 RTT 를 잴 수 있다.
            long sentAt = Stopwatch.GetTimestamp();
            Send(PacketProtocol.Ping, BitConverter.GetBytes(sentAt));
        }

        private void ConnectAndRead(string host, int port)
        {
            try
            {
                _tcp.Connect(host, port);
                _stream = _tcp.GetStream();
            }
            catch (Exception e)
            {
                Fail("connect failed: " + e.Message);
                return;
            }

            _connected = true;
            Enqueue(() =>
            {
                var handler = Connected;
                if (handler != null) handler();
            });

            try
            {
                ReadLoop();
            }
            catch (Exception e)
            {
                Fail("read error: " + e.Message);
            }
        }

        private void ReadLoop()
        {
            var header = new byte[PacketProtocol.HeaderSize];
            while (_closedFlag == 0)
            {
                if (!ReadExact(header, header.Length))
                {
                    Fail("server closed the connection");
                    return;
                }

                ushort size, type;
                PacketProtocol.DecodeHeader(header, out size, out type);
                if (size > PacketProtocol.MaxPayloadSize)
                {
                    Fail("invalid packet size: " + size);
                    return;
                }

                var payload = new byte[size];
                if (size > 0 && !ReadExact(payload, size))
                {
                    Fail("server closed the connection");
                    return;
                }

                ushort packetType = type;
                byte[] packetPayload = payload;
                Enqueue(() => OnPacket(packetType, packetPayload));
            }
        }

        private bool ReadExact(byte[] buffer, int count)
        {
            int offset = 0;
            while (offset < count)
            {
                int read = _stream.Read(buffer, offset, count - offset);
                if (read <= 0)
                {
                    return false;
                }
                offset += read;
            }
            return true;
        }

        private void OnPacket(ushort type, byte[] payload)
        {
            if (type == PacketProtocol.Pong && payload.Length == 8)
            {
                long sentAt = BitConverter.ToInt64(payload, 0);
                LastRttMs = (Stopwatch.GetTimestamp() - sentAt) * 1000.0 / Stopwatch.Frequency;
                PongCount++;
            }

            var handler = PacketReceived;
            if (handler != null) handler(type, payload);
        }

        private void Enqueue(Action action)
        {
            _mainThreadQueue.Enqueue(action);
        }

        /// <summary>연결을 닫고 Disconnected 를 한 번만 알린다.</summary>
        private void Fail(string reason)
        {
            if (Interlocked.Exchange(ref _closedFlag, 1) == 1)
            {
                return;
            }

            _connected = false;
            try
            {
                if (_tcp != null) _tcp.Close();
            }
            catch (Exception)
            {
                // 이미 닫힌 소켓은 무시한다.
            }

            Enqueue(() =>
            {
                var handler = Disconnected;
                if (handler != null) handler(reason);
            });
        }
    }
}
