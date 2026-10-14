using System.Collections.Concurrent;

namespace DemoShop.Services;

public sealed class SessionStore
{
    private static readonly ConcurrentDictionary<string, DateTimeOffset> Sessions = new();

    public void Touch(string sessionId)
    {
        Sessions.TryAdd(sessionId, DateTimeOffset.UtcNow);
    }

    public void End(string sessionId)
    {
        Sessions.TryRemove(sessionId, out _);
    }
}
