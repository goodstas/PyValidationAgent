namespace DemoShop.Services;

public sealed class ReportCache
{
    private static readonly Dictionary<string, string> Reports = new();
    private static readonly object Gate = new();

    public string GetOrAdd(string key)
    {
        lock (Gate)
        {
            if (!Reports.TryGetValue(key, out var report))
            {
                report = $"Report for {key} generated at {DateTimeOffset.UtcNow:O}";
                Reports.Add(key, report);
            }

            return report;
        }
    }
}
