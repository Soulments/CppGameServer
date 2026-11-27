using System;

namespace CppGameServer.Network
{
    /// <summary>
    /// 서버와 같은 패킷 형식 (docs/protocol.md 참고).
    /// [payloadSize u16][type u16][payload], little-endian.
    /// </summary>
    public static class PacketProtocol
    {
        public const int HeaderSize = 4;
        public const int MaxPayloadSize = 4096;

        // 값은 docs/protocol.md 와 server/src/net/Packet.h 와 같아야 한다.
        public const ushort Ping = 1;
        public const ushort Pong = 2;

        public const ushort LoginRequest = 3;
        public const ushort LoginResponse = 4;
        public const ushort JoinRoomRequest = 5;
        public const ushort JoinRoomResponse = 6;
        public const ushort PlayerJoined = 7;
        public const ushort PlayerLeft = 8;

        public const ushort MoveInput = 9;
        public const ushort WorldSnapshot = 10;

        public static byte[] Encode(ushort type, byte[] payload)
        {
            int size = payload == null ? 0 : payload.Length;
            if (size > MaxPayloadSize)
            {
                throw new ArgumentException("payload too large: " + size);
            }

            var buffer = new byte[HeaderSize + size];
            buffer[0] = (byte)(size & 0xFF);
            buffer[1] = (byte)((size >> 8) & 0xFF);
            buffer[2] = (byte)(type & 0xFF);
            buffer[3] = (byte)((type >> 8) & 0xFF);
            if (size > 0)
            {
                Buffer.BlockCopy(payload, 0, buffer, HeaderSize, size);
            }
            return buffer;
        }

        public static void DecodeHeader(byte[] header, out ushort payloadSize, out ushort type)
        {
            payloadSize = (ushort)(header[0] | (header[1] << 8));
            type = (ushort)(header[2] | (header[3] << 8));
        }
    }
}
