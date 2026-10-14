using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Diagnostics;

namespace SecureYourCode.PerformanceAnalyzer.Tests;

internal static class AnalyzerHarness
{
    private static readonly Lazy<ImmutableArray<MetadataReference>> References = new(() =>
    {
        var tpa = (string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!;
        return tpa.Split(Path.PathSeparator)
            .Where(p => Path.GetFileName(p).StartsWith("System", StringComparison.Ordinal)
                        || Path.GetFileName(p) is "mscorlib.dll" or "netstandard.dll")
            .Select(p => (MetadataReference)MetadataReference.CreateFromFile(p))
            .ToImmutableArray();
    });

    /// <summary>Local stubs so analyzer tests can exercise EF async APIs; DemoShop itself has no EF reference.</summary>
    public const string EfStubs = """
        namespace Microsoft.EntityFrameworkCore
        {
            using System.Collections;
            using System.Collections.Generic;
            using System.Linq;
            using System.Linq.Expressions;
            using System.Threading;
            using System.Threading.Tasks;

            public abstract class DbSet<T> : IQueryable<T> where T : class
            {
                public abstract System.Type ElementType { get; }
                public abstract Expression Expression { get; }
                public abstract IQueryProvider Provider { get; }
                public abstract IEnumerator<T> GetEnumerator();
                IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
                public virtual ValueTask<T?> FindAsync(params object?[]? keyValues) => default;
            }

            public class DbContext
            {
                public virtual int SaveChanges() => 0;
                public virtual Task<int> SaveChangesAsync(CancellationToken cancellationToken = default) => Task.FromResult(0);
            }

            public static class EntityFrameworkQueryableExtensions
            {
                public static Task<List<T>> ToListAsync<T>(this IQueryable<T> source, CancellationToken ct = default) => Task.FromResult(new List<T>());
                public static Task<T?> FirstOrDefaultAsync<T>(this IQueryable<T> source, CancellationToken ct = default) => Task.FromResult<T?>(default);
                public static Task<int> CountAsync<T>(this IQueryable<T> source, CancellationToken ct = default) => Task.FromResult(0);
            }
        }
        """;

    public static async Task<ImmutableArray<Diagnostic>> RunAsync(DiagnosticAnalyzer analyzer, params string[] sources)
    {
        var trees = sources.Select((s, i) => CSharpSyntaxTree.ParseText(s, new CSharpParseOptions(LanguageVersion.Latest), path: $"Test{i}.cs"));
        var compilation = CSharpCompilation.Create(
            "AnalyzerTest",
            trees,
            References.Value,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, nullableContextOptions: NullableContextOptions.Enable));

        var errors = compilation.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
        Assert.True(errors.Count == 0, "Test source does not compile:\n" + string.Join("\n", errors));

        var withAnalyzers = compilation.WithAnalyzers(ImmutableArray.Create(analyzer));
        var diagnostics = await withAnalyzers.GetAnalyzerDiagnosticsAsync();
        return diagnostics.OrderBy(d => d.Location.SourceSpan.Start).ToImmutableArray();
    }

    public static int Line(Diagnostic diagnostic) => diagnostic.Location.GetLineSpan().StartLinePosition.Line + 1;
}
