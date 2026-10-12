using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.Diagnostics;
using Microsoft.CodeAnalysis.Operations;

namespace SecureYourCode.PerformanceAnalyzer;

/// <summary>
/// PERF001: query-executing EF Core / IQueryable calls and repository calls executed directly in a loop body.
/// Detection boundary (v2.3.1): query expressions and LINQ Select lambdas are not inspected; calls inside a
/// lambda or local function merely declared in a loop are not attributed to the loop.
/// </summary>
[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class Perf001QueryAmplificationAnalyzer : DiagnosticAnalyzer
{
    private static readonly ImmutableHashSet<string> QueryExecutingMethods = ImmutableHashSet.Create(
        "ToList", "ToListAsync",
        "First", "FirstAsync", "FirstOrDefault", "FirstOrDefaultAsync",
        "Single", "SingleAsync", "SingleOrDefault", "SingleOrDefaultAsync",
        "Count", "CountAsync",
        "FindAsync", "SaveChanges", "SaveChangesAsync");

    private const string EfNamespace = "Microsoft.EntityFrameworkCore";

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => ImmutableArray.Create(Descriptors.Perf001);

    public override void Initialize(AnalysisContext context)
    {
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.EnableConcurrentExecution();
        context.RegisterOperationAction(AnalyzeInvocation, OperationKind.Invocation);
    }

    private static void AnalyzeInvocation(OperationAnalysisContext context)
    {
        var invocation = (IInvocationOperation)context.Operation;
        if (!IsDirectlyInLoopBody(invocation))
        {
            return;
        }

        var method = invocation.TargetMethod;
        if (IsQueryExecuting(invocation) || IsRepositoryCall(invocation))
        {
            context.ReportDiagnostic(Diagnostic.Create(Descriptors.Perf001, invocation.Syntax.GetLocation(), method.Name));
        }
    }

    internal static bool IsDirectlyInLoopBody(IOperation operation)
    {
        var child = operation;
        for (var parent = operation.Parent; parent is not null; child = parent, parent = parent.Parent)
        {
            switch (parent)
            {
                case IAnonymousFunctionOperation:
                case ILocalFunctionOperation:
                    return false;
                case ILoopOperation loop when ReferenceEquals(loop.Body, child):
                    return true;
            }
        }

        return false;
    }

    private static bool IsQueryExecuting(IInvocationOperation invocation)
    {
        var method = invocation.TargetMethod;
        if (!QueryExecutingMethods.Contains(method.Name))
        {
            return false;
        }

        var receiver = OperationHelpers.Receiver(invocation);
        var receiverType = receiver?.Type;

        if (method.Name is "SaveChanges" or "SaveChangesAsync")
        {
            return OperationHelpers.IsOrDerivesFrom(receiverType, EfNamespace, "DbContext")
                   || OperationHelpers.IsOrDerivesFrom(method.ContainingType, EfNamespace, "DbContext");
        }

        if (method.Name == "FindAsync")
        {
            return OperationHelpers.IsOrDerivesFrom(receiverType, EfNamespace, "DbSet`1")
                   || OperationHelpers.IsOrDerivesFrom(method.ContainingType, EfNamespace, "DbSet`1");
        }

        // ToList()/First()/Count() etc. usually bind to Enumerable.*, so the decisive check is the
        // receiver's static type implementing IQueryable<T> (DbSet<T> does), not the containing type.
        return OperationHelpers.ImplementsGenericInterface(receiverType, "System.Linq", "IQueryable`1")
               || OperationHelpers.IsOrDerivesFrom(receiverType, EfNamespace, "DbSet`1");
    }

    private static bool IsRepositoryCall(IInvocationOperation invocation)
    {
        var method = invocation.TargetMethod;
        if (method.IsStatic || method.IsExtensionMethod || invocation.Instance is null)
        {
            return false;
        }

        var receiverType = OperationHelpers.Unwrap(invocation.Instance).Type;
        if (receiverType is null)
        {
            return false;
        }

        if (receiverType.Name.EndsWith("Repository", System.StringComparison.Ordinal))
        {
            return true;
        }

        foreach (var iface in receiverType.AllInterfaces)
        {
            if (iface.Name.EndsWith("Repository", System.StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }
}
