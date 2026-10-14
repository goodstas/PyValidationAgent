namespace SecureYourCode.PerformanceAnalyzer.Tests;

public class Perf004Tests
{
    private static Task<System.Collections.Immutable.ImmutableArray<Microsoft.CodeAnalysis.Diagnostic>> Run(string code) =>
        AnalyzerHarness.RunAsync(new Perf004StaticCollectionGrowthAnalyzer(), code);

    [Fact]
    public async Task Positive_StaticDictionaryAddWithoutCleanup()
    {
        var d = await Run("""
            using System.Collections.Generic;
            public class ReportCache
            {
                private static readonly Dictionary<string, string> Reports = new();
                public string GetOrAdd(string key)
                {
                    if (!Reports.TryGetValue(key, out var v))
                    {
                        v = key.ToUpperInvariant();
                        Reports.Add(key, v);
                    }
                    return v;
                }
            }
            """);
        var diag = Assert.Single(d);
        Assert.Equal("PERF004", diag.Id);
        Assert.Equal("Static collection 'Reports' grows without observed removal/clear in 'ReportCache': potential memory retention", diag.GetMessage());
        Assert.Equal(10, AnalyzerHarness.Line(diag));
    }

    [Fact]
    public async Task Positive_ConcurrentDictionaryAndListGrowth_IndexerOnDictionary()
    {
        var d = await Run("""
            using System.Collections.Concurrent;
            using System.Collections.Generic;
            public static class Registry
            {
                private static readonly ConcurrentDictionary<int, string> Seen = new();
                private static readonly List<string> Log = new();
                private static Dictionary<string, int> Hits = new();
                public static void Track(int id, string name)
                {
                    Seen.GetOrAdd(id, name);
                    Seen.AddOrUpdate(id, name, (_, _) => name);
                    Log.Add(name);
                    Log.InsertRange(0, new[] { name });
                    Hits[name] = id;
                }
            }
            """);
        Assert.Equal(5, d.Length);
        Assert.All(d, x => Assert.Equal("PERF004", x.Id));
    }

    [Fact]
    public async Task Negative_ListIndexerAssignmentIsNotGrowth()
    {
        var d = await Run("""
            using System.Collections.Generic;
            public static class Slots
            {
                private static readonly List<string> Items = new() { "a", "b" };
                public static void Set(int index, string value) { Items[index] = value; }
            }
            """);
        Assert.Empty(d);
    }

    [Fact]
    public async Task Negative_InstanceCollection_AndStaticWithClearOrRemove()
    {
        var d = await Run("""
            using System.Collections.Concurrent;
            using System.Collections.Generic;
            public class Sessions
            {
                private readonly Dictionary<string, string> _perInstance = new();
                private static readonly Dictionary<string, string> Active = new();
                private static readonly ConcurrentDictionary<string, int> Locks = new();
                public void Add(string k) { _perInstance.Add(k, k); Active[k] = k; Locks.TryAdd(k, 1); }
                public void Reset() { Active.Clear(); }
                public void Release(string k) { Locks.TryRemove(k, out _); }
            }
            """);
        Assert.Empty(d);
    }

    [Fact]
    public async Task Negative_StaticPropertyIsOutOfScope()
    {
        var d = await Run("""
            using System.Collections.Generic;
            public static class Props
            {
                public static Dictionary<string, string> Cache { get; } = new();
                public static void Add(string k) { Cache.Add(k, k); }
            }
            """);
        Assert.Empty(d);
    }
}
