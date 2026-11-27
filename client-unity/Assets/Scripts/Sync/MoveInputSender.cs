using System;

namespace CppGameServer.Sync
{
    /// <summary>
    /// 이동 입력을 서버로 보내는 규칙. Unity API 에 의존하지 않는 순수 C# 이다.
    ///
    /// - 입력이 **바뀔 때만** 보낸다. 서버는 마지막 입력을 다음 입력이 올 때까지 유지하고, TCP 는 순서와 도착을 보장하므로
    ///   누르고 있는 동안 계속 보낼 필요가 없다. 손을 떼면 (0, 0) 을 보내서 멈춘다.
    /// - seq 는 1부터 성공한 전송마다 1씩 늘어난다. 서버는 이전 값보다 작거나 같은 번호를 버린다.
    /// - 전송에 실패하면(연결 전 등) 상태를 확정하지 않아서 다음 호출에서 같은 번호로 다시 시도한다.
    /// - NaN/무한대 입력은 보내지 않는다 (서버도 무시한다).
    /// </summary>
    public sealed class MoveInputSender
    {
        private const float Epsilon = 1e-3f;

        private readonly Func<uint, float, float, bool> _send;
        private float _lastX;
        private float _lastZ;

        /// <param name="send">(seq, dirX, dirZ) 를 전송하고 성공 여부를 돌려준다. 예: lobby.SendMoveInput</param>
        public MoveInputSender(Func<uint, float, float, bool> send)
        {
            if (send == null) throw new ArgumentNullException("send");
            _send = send;
        }

        /// <summary>마지막으로 전송에 성공한 입력 번호 (아직 없으면 0).</summary>
        public uint LastSeq { get; private set; }

        /// <summary>현재 입력을 알린다. 서버에 보냈으면 true.</summary>
        public bool Update(float dirX, float dirZ)
        {
            if (float.IsNaN(dirX) || float.IsNaN(dirZ) || float.IsInfinity(dirX) || float.IsInfinity(dirZ))
            {
                return false;
            }
            if (Math.Abs(dirX - _lastX) < Epsilon && Math.Abs(dirZ - _lastZ) < Epsilon)
            {
                return false;  // 서버가 이미 알고 있는 입력과 같다
            }

            uint seq = LastSeq + 1;
            if (!_send(seq, dirX, dirZ))
            {
                return false;
            }

            LastSeq = seq;
            _lastX = dirX;
            _lastZ = dirZ;
            return true;
        }
    }
}
