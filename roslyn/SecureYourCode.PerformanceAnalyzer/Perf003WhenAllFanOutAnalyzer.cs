using System.Collections.Immutable;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;
using Microsoft.CodeAnalysis.Operations;

namespace SecureYourCode.PerformanceAnalyzer;

/// <summary>
/// PERF003: System.Threading.Tasks.Task.WhenAll(source.Select(...)) where the projection returns Task/Task&lt;T&gt;
/// and the source is not recognised as bounded. No interprocedural size/data-flow analysis is performed.
/// Bounded sources: array/collection literals (directly or via a local initialised with one), and a foreach
/// iteration variable over source.Chunk(constant). source.Chunk(n).Select(...) itself is flagged.
/// </summary>
[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class Perf003WhenAllFanOutAnalyzer : DiagnosticAnalyzer
{
    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => ImmutableArray.Create(Descriptors.Perf003);

    public override void Initialize(AnalysisContext context)
    {
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.EnableConcurrentExecution();
        context.RegisterOperationAction(AnalyzeInvocation, OperationKind.Invocation);
    }

    private static void AnalyzeInvocation(OperationAnalysisContext context)
    {
        var invocation = (IInvocationOperation)context.Operation;
        var method = invocation.TargetMethod;
        if (method.Name != "WhenAll" || !method.IsStatic
            || !OperationHelpers.IsType(method.ContainingType, "System.Threading.Tasks", "Task")
            || invocation.Arguments.Length != 1)
        {
            return;
        }

        var select = FindSelect(invocation.Arguments[0].Value);
        if (select is null)
        {
            return;
        }

        var source = OperationHelpers.Receiver(select);
        if (source is null || IsBounded(source, context.Operation.SemanticModel))
        {
            return;
        }

        context.ReportDiagnostic(Diagnostic.Create(Descriptors.Perf003, invocation.Syntax.GetLocation()));
    }

    /// <summary>Finds an Enumerable.Select returning Task/Task&lt;T&gt;, optionally wrapped in ToArray()/ToList() or a params array.</summary>
    private static IInvocationOperation? FindSelect(IOperation argument)
    {
        var value = OperationHelpers.Unwrap(argument);

        // Task.WhenAll(params Task[]) / params ReadOnlySpan<Task> with exactly one element that is itself
        // an array/list materialisation is bound in normal form; an implicit params array has element initializers.
        if (value is IArrayCreationOperation { Initializer: { ElementValues.Length: 1 } init } && value.IsImplicit)
        {
            value = OperationHelpers.Unwrap(init.ElementValues[0]);
        }

        if (value is IInvocationOperation materialise
            && materialise.TargetMethod.Name is "ToArray" or "ToList"
            && OperationHelpers.IsType(materialise.TargetMethod.ContainingType, "System.Linq", "Enumerable"))
        {
            var inner = OperationHelpers.Receiver(materialise);
            if (inner is null)
            {
                return null;
            }

            value = inner;
        }

        if (value is IInvocationOperation select
            && select.TargetMethod.Name == "Select"
            && OperationHelpers.IsType(select.TargetMethod.ContainingType, "System.Linq", "Enumerable")
            && select.TargetMethod.TypeArguments.Length == 2
            && OperationHelpers.IsTaskType(select.TargetMethod.TypeArguments[1]))
        {
            return select;
        }

        return null;
    }

    private static bool IsBounded(IOperation source, SemanticModel? semanticModel)
    {
        source = OperationHelpers.Unwrap(source);
        switch (source)
        {
            case IArrayCreationOperation { Initializer: not null }:
                return true;
            case ICollectionExpressionOperation collection:
                return collection.Elements.All(e => e is not ISpreadOperation);
            case ILocalReferenceOperation local:
                return IsBoundedLocal(local.Local, semanticModel);
            default:
                return false;
        }
    }

    private static bool IsBoundedLocal(ILocalSymbol local, SemanticModel? semanticModel)
    {
        foreach (var reference in local.DeclaringSyntaxReferences)
        {
            var syntax = reference.GetSyntax();

            // foreach (var batch in source.Chunk(constant)) { ... batch.Select(...) ... }
            if (syntax is ForEachStatementSyntax forEach && semanticModel is not null && forEach.SyntaxTree == semanticModel.SyntaxTree)
            {
                // Locals are method-scoped, so their declaration lives in the analysed syntax tree.
                var model = semanticModel;
                if (model.GetOperation(forEach.Expression) is { } collection
                    && OperationHelpers.Unwrap(collection) is IInvocationOperation chunk
                    && chunk.TargetMethod.Name == "Chunk"
                    && OperationHelpers.IsType(chunk.TargetMethod.ContainingType, "System.Linq", "Enumerable")
                    && chunk.Arguments.Length == 2
                    && OperationHelpers.Unwrap(chunk.Arguments[1].Value).ConstantValue.HasValue)
                {
                    return true;
                }

                return false;
            }

            // var tasks = new[] { a, b }; / int[] ids = [1, 2, 3];
            if (syntax is VariableDeclaratorSyntax { Initializer.Value: { } initializer } && semanticModel is not null && initializer.SyntaxTree == semanticModel.SyntaxTree)
            {
                var model = semanticModel;
                if (model.GetOperation(initializer) is { } initOperation)
                {
                    var init = OperationHelpers.Unwrap(initOperation);
                    if (init is IArrayCreationOperation { Initializer: not null })
                    {
                        return true;
                    }

                    if (init is ICollectionExpressionOperation collection && collection.Elements.All(e => e is not ISpreadOperation))
                    {
                        return true;
                    }
                }
            }
        }

        return false;
    }
}
