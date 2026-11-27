// UnityEngine 최소 스텁: Unity 에 의존하는 스크립트를 Unity 없이 "컴파일만" 하기 위한 것이다 (실행하지 않는다).
// 실제 Unity API 와 시그니처가 다를 수 있으므로, 여기서 컴파일된다고 Unity 에서도 컴파일된다는 보장은 없다.
using System;

namespace UnityEngine
{
    public class Object
    {
        public string name;
        public static void Destroy(Object obj) { }
    }

    public class Component : Object
    {
        public Transform transform;
        public T GetComponent<T>() { return default(T); }
    }

    public class Behaviour : Component { }
    public class MonoBehaviour : Behaviour { }

    [AttributeUsage(AttributeTargets.Field)] public class SerializeFieldAttribute : Attribute { }
    [AttributeUsage(AttributeTargets.Field)] public class TooltipAttribute : Attribute { public TooltipAttribute(string text) { } }
    [AttributeUsage(AttributeTargets.Class)] public class RequireComponentAttribute : Attribute { public RequireComponentAttribute(Type type) { } }

    public struct Vector2
    {
        public float x, y;
        public Vector2(float x, float y) { this.x = x; this.y = y; }
        public static Vector2 operator +(Vector2 a, Vector2 b) { return new Vector2(a.x + b.x, a.y + b.y); }
        public static Vector2 ClampMagnitude(Vector2 v, float max) { return v; }
    }

    public struct Vector3
    {
        public float x, y, z;
        public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
    }

    public class Transform : Component
    {
        public Vector3 position;
    }

    public enum PrimitiveType { Cube }

    public class GameObject : Object
    {
        public Transform transform;
        public static GameObject CreatePrimitive(PrimitiveType type) { return new GameObject(); }
    }

    public static class Debug
    {
        public static void Log(object message) { }
        public static void LogWarning(object message) { }
    }

    public static class Application { public static bool runInBackground; }
    public static class GUILayout { public static void Label(string text) { } }
    public static class Random { public static int Range(int min, int max) { return min; } }
    public static class Input { public static float GetAxisRaw(string axis) { return 0f; } }
    public static class Time { public static double realtimeSinceStartupAsDouble { get { return 0; } } }
}
