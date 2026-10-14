using System.Collections.Concurrent;
using System.Diagnostics;

namespace DemoShop.Services;

public interface IJobLauncher
{
    string Enqueue(ProcessStartInfo startInfo);
}

/// <summary>Records requested jobs only. DemoShop never starts processes.</summary>
public sealed class QueuedJobLauncher : IJobLauncher
{
    private readonly ConcurrentQueue<ProcessStartInfo> _pending = new();

    public string Enqueue(ProcessStartInfo startInfo)
    {
        _pending.Enqueue(startInfo);
        return $"queued:{_pending.Count}";
    }
}
