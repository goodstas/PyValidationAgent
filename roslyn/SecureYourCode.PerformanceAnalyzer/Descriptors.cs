using Microsoft.CodeAnalysis;

namespace SecureYourCode.PerformanceAnalyzer;

internal static class Descriptors
{
    private const string Category = "Performance";

    public static readonly DiagnosticDescriptor Perf001 = new(
        id: "PERF001",
        title: "Possible database/repository query amplification",
        messageFormat: "'{0}' is invoked inside a loop: potential database/repository call amplification",
        category: Category,
        defaultSeverity: DiagnosticSeverity.Warning,
        isEnabledByDefault: true,
        description: "A query-executing EF Core/IQueryable method or a repository method is invoked directly inside a loop body. This is a candidate only: implementations may cache or batch.");

    public static readonly DiagnosticDescriptor Perf003 = new(
        id: "PERF003",
        title: "Input-scaled Task.WhenAll fan-out",
        messageFormat: "Task.WhenAll creates potentially input-sized concurrency: review fan-out limits",
        category: Category,
        defaultSeverity: DiagnosticSeverity.Warning,
        isEnabledByDefault: true,
        description: "Task.WhenAll over a Select projection of an enumerable not recognised as bounded starts one task per element.");

    public static readonly DiagnosticDescriptor Perf004 = new(
        id: "PERF004",
        title: "Potentially unbounded static collection growth",
        messageFormat: "Static collection '{0}' grows without observed removal/clear in '{1}': potential memory retention",
        category: Category,
        defaultSeverity: DiagnosticSeverity.Warning,
        isEnabledByDefault: true,
        description: "A static Dictionary/ConcurrentDictionary/List field is grown but no removal or Clear of the same field is observed in its containing type.");
}
