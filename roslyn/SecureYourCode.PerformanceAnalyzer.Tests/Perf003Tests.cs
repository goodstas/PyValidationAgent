namespace SecureYourCode.PerformanceAnalyzer.Tests;

public class Perf003Tests
{
    private const string Prelude = """
        using System.Collections.Generic;
        using System.Linq;
        using System.Threading;
        using System.Threading.Tasks;
        public static class Io
        {
            public static Task SendAsync(string r) => Task.CompletedTask;
            public static Task<int> CountAsync(string r) => Task.FromResult(1);
            public static Task ProcessAsync(string[] batch) => Task.CompletedTask;
        }
        public static class Fake { public static Task WhenAll(IEnumerable<Task> t) => Task.CompletedTask; }
        """;

    private static Task<System.Collections.Immutable.ImmutableArray<Microsoft.CodeAnalysis.Diagnostic>> Run(string code) =>
        AnalyzerHarness.RunAsync(new Perf003WhenAllFanOutAnalyzer(), Prelude, code);

    [Fact]
    public async Task Positive_AsyncLambda_MethodGroup_ToArray_ToList()
    {
        var d = await Run("""
            using System.Collections.Generic;
            using System.Linq;
            using System.Threading.Tasks;
            public class S
            {
                private readonly List<string> _field = new();
                public async Task Run(IEnumerable<string> recipients)
                {
                    await Task.WhenAll(recipients.Select(async r => await Io.SendAsync(r)));
                    await Task.WhenAll(recipients.Select(Io.SendAsync));
                    await Task.WhenAll(recipients.Select(r => Io.CountAsync(r)).ToArray());
                    await Task.WhenAll(_field.Select(Io.SendAsync).ToList());
                }
            }
            """);
        Assert.Equal(4, d.Length);
        Assert.All(d, x => Assert.Equal("PERF003", x.Id));
        Assert.All(d, x => Assert.Equal("Task.WhenAll creates potentially input-sized concurrency: review fan-out limits", x.GetMessage()));
    }

    [Fact]
    public async Task Positive_ChunkSelectInsideWhenAll()
    {
        var d = await Run("""
            using System.Collections.Generic;
            using System.Linq;
            using System.Threading.Tasks;
            public class S
            {
                public Task Run(IEnumerable<string> source) =>
                    Task.WhenAll(source.Chunk(10).Select(batch => Io.ProcessAsync(batch)));
            }
            """);
        Assert.Equal("PERF003", Assert.Single(d).Id);
    }

    [Fact]
    public async Task Negative_SequentialChunkedBatches()
    {
        var d = await Run("""
            using System.Collections.Generic;
            using System.Linq;
            using System.Threading.Tasks;
            public class S
            {
                public async Task Run(IEnumerable<string> source)
                {
                    foreach (var batch in source.Chunk(10))
                    {
                        await Task.WhenAll(batch.Select(Io.SendAsync));
                    }
                }
            }
            """);
        Assert.Empty(d);
    }

    [Fact]
    public async Task Negative_FixedLiteral_LocalArray_ParallelForEach_UserDefinedWhenAll()
    {
        var d = await Run("""
            using System.Collections.Generic;
            using System.Linq;
            using System.Threading;
            using System.Threading.Tasks;
            public class S
            {
                public async Task Run(IEnumerable<string> source)
                {
                    await Task.WhenAll(new[] { "a", "b" }.Select(Io.SendAsync));
                    var fixedTargets = new[] { "primary", "replica" };
                    await Task.WhenAll(fixedTargets.Select(Io.SendAsync));
                    string[] literal = ["x", "y", "z"];
                    await Task.WhenAll(literal.Select(Io.SendAsync));
                    await Task.WhenAll(Io.SendAsync("a"), Io.SendAsync("b"));
                    await Parallel.ForEachAsync(source, new ParallelOptions { MaxDegreeOfParallelism = 4 }, async (r, ct) => await Io.SendAsync(r));
                    await Fake.WhenAll(source.Select(Io.SendAsync));
                    var lengths = await Task.WhenAll(source.Count() > 0 ? new[] { Io.CountAsync("a") } : new Task<int>[0]);
                }
            }
            """);
        Assert.Empty(d);
    }
}
